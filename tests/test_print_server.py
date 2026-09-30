import subprocess
import sys
from pathlib import Path

import pytest

ADDON = Path(__file__).parents[1] / "label_studio"
sys.path.insert(0, str(ADDON))
import print_server


PPD = """*DefaultPageSize: w167h288
*DefaultPageRegion: w167h288
*PageSize w162h90/11354 Multi-Purpose: "<</PageSize[162 90]>>setpagedevice"
*PageSize w79h252.2/99010 Standard Address: "<</PageSize[79 252]>>setpagedevice"
*PageSize w167h288/30256 Shipping: "<</PageSize[167 288]>>setpagedevice"
*PageRegion w162h90/11354 Multi-Purpose: "<</PageSize[162 90]>>setpagedevice"
*PageRegion w167h288/30256 Shipping: "<</PageSize[167 288]>>setpagedevice"
*ImageableArea w167h288/30256 Shipping: "4.08 4.32 163.68 271.20"
*PaperDimension w162h90/11354 Multi-Purpose: "162.00 90.00"
*PaperDimension w167h288/30256 Shipping: "166.56 288.00"
*OpenUI *Resolution: PickOne
"""


def test_only_favourite_sizes_stay_in_the_ppd():
    filtered = print_server.filter_page_sizes(PPD, {"w162h90", "w79h252.2"}, "w162h90")
    assert "30256" not in filtered
    assert "*DefaultPageSize: w162h90" in filtered and "*DefaultPageRegion: w162h90" in filtered
    assert "*PageSize w79h252.2/99010" in filtered and "*OpenUI *Resolution" in filtered


def test_favourites_are_applied_to_the_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(print_server, "ORIGINAL_PPD", tmp_path / "original.ppd")
    monkeypatch.setattr(print_server, "FILTERED_PPD", tmp_path / "favorites.ppd")
    (tmp_path / "original.ppd").write_text(PPD)
    calls = []
    monkeypatch.setattr(print_server, "_run", lambda *args, **kw: calls.append(args))
    used = print_server.apply_label_sizes(["99010", "11354", "not-a-label"], "11354")
    assert used == ["w79h252.2", "w162h90"]
    assert calls == [("lpadmin", "-p", "DYMO", "-P", str(tmp_path / "favorites.ppd"))]
    assert "*DefaultPageSize: w162h90" in (tmp_path / "favorites.ppd").read_text()


def test_driver_follows_the_detected_model(monkeypatch):
    listing = "\n".join([
        "dymo:0/cups/model/lw400.ppd DYMO LabelWriter 400",
        "dymo:0/cups/model/lw450.ppd DYMO LabelWriter 450",
        "dymo:0/cups/model/lw450t.ppd DYMO LabelWriter 450 Turbo",
        "drv:///sample.drv/generic.ppd Generic PostScript Printer",
    ])
    monkeypatch.setattr(print_server, "_run", lambda *args, **kw: subprocess.CompletedProcess(args, 0, listing, ""))
    assert print_server._choose_driver("LabelWriter 450 Turbo") == "dymo:0/cups/model/lw450t.ppd"
    assert print_server._choose_driver("LabelWriter 400") == "dymo:0/cups/model/lw400.ppd"
    assert print_server._choose_driver(None) == "dymo:0/cups/model/lw450.ppd"


@pytest.mark.parametrize("from_file", [False, True])
def test_cups_backend_writes_job_to_the_device(tmp_path, from_file):
    device, job = tmp_path / "lp0", tmp_path / "job"
    job.write_bytes(b"\x1b" * 10 + b"label")
    env = {"DEVICE_URI": f"dymo:{device}", "DYMO_LOCK_FILE": str(tmp_path / "lock")}
    args = [sys.executable, str(ADDON / "cups-backend-dymo"), "1", "user", "title", "2", ""]
    result = subprocess.run(args + ([str(job)] if from_file else []), input=None if from_file else job.read_bytes(), env=env, capture_output=True)
    assert result.returncode == 0, result.stderr
    # With a file the backend prints the copies itself; from stdin the filters already did.
    assert device.read_bytes() == job.read_bytes() * (2 if from_file else 1)


def test_cups_backend_asks_cups_to_retry_without_device(tmp_path):
    env = {"DEVICE_URI": f"dymo:{tmp_path}/missing/lp0", "DYMO_LOCK_FILE": str(tmp_path / "lock")}
    result = subprocess.run([sys.executable, str(ADDON / "cups-backend-dymo"), "1", "u", "t", "1", ""], input=b"x", env=env, capture_output=True)
    assert result.returncode == 6
