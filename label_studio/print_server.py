"""Share the LabelWriter on the network through CUPS, announced over Bonjour/mDNS.

The web app switches sharing on and off. Starting runs D-Bus, Avahi and CUPS as child
processes and creates a shared queue that uses DYMO's CUPS driver and the ``dymo``
backend; stopping ends them, which also withdraws the network announcement.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
import socket
import subprocess
import threading
import time

from label_renderer import LABEL_SIZES


log = logging.getLogger("print_server")

# The driver's PPD as created, and the copy offered to the network with only the favourite sizes.
ORIGINAL_PPD = Path("/run/dymo-original.ppd")
FILTERED_PPD = Path("/run/dymo-favorites.ppd")
PAGE_SIZE_ENTRIES = ("PageSize", "PageRegion", "ImageableArea", "PaperDimension")
QUEUE = "DYMO"
QUEUE_DESCRIPTION = "DYMO LabelWriter"
AVAHI_HOST_NAME = "dymo-labels"
DEFAULT_MODEL = "LabelWriter 450"

CUPSD_CONF = """\
LogLevel warn
MaxLogSize 1m
Listen 0.0.0.0:631
Listen /run/cups/cups.sock
# Accept any Host header, e.g. the add-on's .local name or the Home Assistant host name.
ServerAlias *
Browsing On
BrowseLocalProtocols dnssd
DefaultShared Yes
WebInterface Yes
DefaultAuthType Basic

<Location />
  Order allow,deny
  Allow all
</Location>
<Location /admin>
  Order allow,deny
  Allow localhost
</Location>

<Policy default>
  JobPrivateAccess default
  JobPrivateValues default
  SubscriptionPrivateAccess default
  SubscriptionPrivateValues default
  <Limit Create-Job Print-Job Print-URI Validate-Job>
    Order deny,allow
  </Limit>
  <Limit Send-Document Send-URI Hold-Job Release-Job Restart-Job Purge-Jobs Set-Job-Attributes Create-Job-Subscription Renew-Subscription Cancel-Subscription Get-Notifications Reprocess-Job Cancel-Current-Job Suspend-Current-Job Resume-Job Cancel-My-Jobs Close-Job CUPS-Move-Job CUPS-Get-Document>
    Require user @OWNER @SYSTEM
    Order deny,allow
  </Limit>
  <Limit CUPS-Add-Modify-Printer CUPS-Delete-Printer CUPS-Add-Modify-Class CUPS-Delete-Class CUPS-Set-Default CUPS-Get-Devices Pause-Printer Resume-Printer Enable-Printer Disable-Printer Pause-Printer-After-Current-Job Hold-New-Jobs Release-Held-New-Jobs Deactivate-Printer Activate-Printer Restart-Printer Shutdown-Printer Startup-Printer Promote-Job Schedule-Job-After Cancel-Jobs CUPS-Accept-Jobs CUPS-Reject-Jobs>
    AuthType Default
    Require user @SYSTEM
    Order deny,allow
  </Limit>
  <Limit Cancel-Job CUPS-Authenticate-Job>
    Require user @OWNER @SYSTEM
    Order deny,allow
  </Limit>
  <Limit All>
    Order deny,allow
  </Limit>
</Policy>
"""

AVAHI_CONF = """\
[server]
host-name={host_name}
use-ipv4=yes
use-ipv6=no
{interfaces}enable-dbus=yes
ratelimit-interval-usec=1000000
ratelimit-burst=1000

[wide-area]
enable-wide-area=no

[publish]
publish-hinfo=no
publish-workstation=no
"""


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=check, capture_output=True, text=True)


def _lan_interface() -> str | None:
    """The interface of the default route: the one computers on the LAN can reach."""
    try:
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            fields = line.split()
            if len(fields) > 2 and fields[1] == "00000000":
                return fields[0]
    except OSError:
        pass
    return None


def _lan_address() -> str | None:
    """The host's LAN IP address, as seen when talking to the outside world."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))  # TEST-NET address; nothing is sent
            return probe.getsockname()[0]
    except OSError:
        return None


def _usb_model(device: str) -> str | None:
    """Read the model from the printer's IEEE 1284 ID, e.g. 'LabelWriter 450'."""
    ieee_id = Path("/sys/class/usbmisc") / Path(device).name / "device" / "ieee1284_id"
    try:
        match = re.search(r"(?:MDL|MODEL):([^;]+)", ieee_id.read_text())
    except OSError:
        return None
    return match.group(1).strip() if match else None


def _choose_driver(model: str | None) -> str:
    """Pick the DYMO PPD from ``lpinfo -m`` that best matches the printer model."""
    drivers = []
    for line in _run("lpinfo", "-m").stdout.splitlines():
        name, _, description = line.partition(" ")
        if "labelwriter" in description.lower():
            drivers.append((name, description))
    if not drivers:
        raise RuntimeError("DYMO LabelWriter driver not found (printer-driver-dymo)")
    for wanted in filter(None, (model, DEFAULT_MODEL)):
        exact = [name for name, description in drivers if description.lower().endswith(wanted.lower())]
        if exact:
            return exact[0]
        partial = [name for name, description in drivers if wanted.lower() in description.lower()]
        if partial:
            return partial[0]
    return drivers[0][0]


def filter_page_sizes(ppd: str, keywords: set[str], default: str) -> str:
    """Keep only the given page sizes in a PPD and make ``default`` the default size."""
    lines = []
    for line in ppd.splitlines(keepends=True):
        entry = re.match(rf"\*({'|'.join(PAGE_SIZE_ENTRIES)})\s+([^/\s:]+)", line)
        if entry and entry.group(2) not in keywords:
            continue
        default_entry = re.match(rf"\*Default({'|'.join(PAGE_SIZE_ENTRIES)}):", line)
        if default_entry:
            line = f"*Default{default_entry.group(1)}: {default}\n"
        lines.append(line)
    return "".join(lines)


def apply_label_sizes(label_ids: list[str], default_id: str | None) -> list[str]:
    """Offer only the favourite labels to network clients; returns the page size keywords used."""
    original = ORIGINAL_PPD.read_text(errors="replace")
    available = set(re.findall(r"^\*PageSize\s+([^/\s:]+)", original, re.MULTILINE))
    sizes = [LABEL_SIZES[i] for i in label_ids if i in LABEL_SIZES and LABEL_SIZES[i].ppd in available]
    if not sizes:
        log.warning("None of the favourite labels are in the driver; offering all its sizes")
        return sorted(available)
    default = LABEL_SIZES[default_id] if default_id in label_ids and LABEL_SIZES.get(default_id) in sizes else sizes[0]
    FILTERED_PPD.write_text(filter_page_sizes(original, {size.ppd for size in sizes}, default.ppd))
    _run("lpadmin", "-p", QUEUE, "-P", str(FILTERED_PPD))
    return [size.ppd for size in sizes]


def _wait_for_cups(timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if "is running" in _run("lpstat", "-r", check=False).stdout:
            return
        time.sleep(0.5)
    raise RuntimeError("CUPS did not start")


def _wait_for(path: str, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while not Path(path).exists():
        if time.monotonic() > deadline:
            raise RuntimeError(f"{path} did not appear")
        time.sleep(0.2)


def create_queue(device: str, favorites: list[str], default: str) -> dict:
    model = _usb_model(device)
    driver = _choose_driver(model)
    log.info("Sharing %s as %r with driver %s", model or "LabelWriter (model unknown)", QUEUE_DESCRIPTION, driver)
    _run(
        "lpadmin", "-p", QUEUE, "-E",
        "-v", f"dymo:{device}",
        "-m", driver,
        "-D", QUEUE_DESCRIPTION,
        "-L", "Home Assistant",
        "-o", "printer-is-shared=true",
        "-o", "printer-error-policy=retry-job",
    )
    ORIGINAL_PPD.write_text(Path(f"/etc/cups/ppd/{QUEUE}.ppd").read_text(errors="replace"))
    page_sizes = apply_label_sizes(favorites, default)
    _run("cupsenable", QUEUE)
    _run("cupsaccept", QUEUE)
    address = _lan_address()
    return {
        "enabled": True,
        "name": QUEUE_DESCRIPTION,
        "model": model,
        "driver": driver,
        "page_sizes": page_sizes,
        "uri": f"ipp://{address or AVAHI_HOST_NAME + '.local'}:631/printers/{QUEUE}",
    }


class PrintServer:
    """The network printer: D-Bus, Avahi and CUPS running as child processes."""

    def __init__(self) -> None:
        self.status: dict = {"enabled": False}
        self._processes: list[subprocess.Popen] = []
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return bool(self._processes)

    def _spawn(self, *args: str) -> None:
        self._processes.append(subprocess.Popen(args))

    def start(self, device: str, favorites: list[str], default: str) -> None:
        with self._lock:
            if self._processes:
                return
            self.status = {"enabled": True, "starting": True}
            try:
                for stale in ("/run/dbus/pid", "/run/dbus/system_bus_socket", "/run/avahi-daemon/pid"):
                    Path(stale).unlink(missing_ok=True)
                Path("/run/dbus").mkdir(parents=True, exist_ok=True)
                _run("dbus-uuidgen", "--ensure")
                self._spawn("dbus-daemon", "--system", "--nofork", "--nopidfile")
                _wait_for("/run/dbus/system_bus_socket")

                interface = _lan_interface()
                Path("/etc/avahi/avahi-daemon.conf").write_text(AVAHI_CONF.format(
                    host_name=AVAHI_HOST_NAME,
                    # Only announce on the LAN, not on Home Assistant's internal Docker networks.
                    interfaces=f"allow-interfaces={interface}\n" if interface else "",
                ))
                self._spawn("avahi-daemon", "--no-chroot")

                Path("/etc/cups/cupsd.conf").write_text(CUPSD_CONF)
                Path("/run/cups").mkdir(parents=True, exist_ok=True)
                self._spawn("cupsd", "-f")
                _wait_for_cups()
                self.status = create_queue(device, favorites, default)
            except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
                detail = (getattr(exc, "stderr", "") or "").strip()
                log.error("Network printer could not start: %s %s", exc, detail)
                self._stop_processes()
                self.status = {"enabled": True, "error": str(exc)}

    def stop(self) -> None:
        with self._lock:
            self._stop_processes()
            self.status = {"enabled": False}

    def _stop_processes(self) -> None:
        # Newest first: CUPS, then Avahi (which withdraws the announcement), then D-Bus.
        for process in reversed(self._processes):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        self._processes = []
