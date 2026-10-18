"""
Export the CropSCOUT A08 assembly from the SolidWorks that is running on this PC into
meshes/cropscout_full.stl (binary, millimetres, CAD origin kept, whole assembly in one file),
using the SolidWorks COM API. Nothing to click in SolidWorks.

    .venv\\Scripts\\python.exe export_stl_from_solidworks.py [path\\to\\CropSCOUT_Robot_A08_Raised_Side_Spray.SLDASM]

Needs:  pip install pywin32   (6_EXPORT_CAD_FROM_SOLIDWORKS.bat does it)
"""
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "meshes" / "cropscout_full.stl"
ASM_NAME = "CropSCOUT_Robot_A08_Raised_Side_Spray.SLDASM"
CANDIDATES = [
    Path.home() / "Desktop" / "CropSCOUT_A08_new" / "CropSCOUT_A08_Raised_Side_Spray" / ASM_NAME,
    Path.home() / "Desktop" / "CropSCOUT_A08_Raised_Side_Spray" / ASM_NAME,
    HERE.parent / "CropSCOUT_A08_Raised_Side_Spray" / ASM_NAME,
]

# swconst.swUserPreferenceToggle_e / swUserPreferenceIntegerValue_e / swLengthUnit_e
swSTLBinaryFormat, swSTLShowInfoOnSave, swSTLComponentsIntoOneFile, swSTLDontTranslateToPositive = 17, 18, 55, 174
swDocASSEMBLY = 2


def main():
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        sys.exit("pywin32 is missing: run  .venv\\Scripts\\python.exe -m pip install pywin32")
    pythoncom.CoInitialize()
    try:
        sw = win32com.client.GetActiveObject("SldWorks.Application")
        print("connected to the running SolidWorks")
    except Exception:
        print("SolidWorks is not running - starting it (this can take a minute) ...")
        sw = win32com.client.Dispatch("SldWorks.Application")
        sw.Visible = True
        time.sleep(5)

    asm = Path(sys.argv[1]) if len(sys.argv) > 1 else next((c for c in CANDIDATES if c.exists()), None)
    if asm is None:
        sys.exit(f"assembly not found; pass its path:  export_stl_from_solidworks.py C:\\...\\{ASM_NAME}")

    # use the document if it is already open, otherwise open it
    model = sw.ActiveDoc
    if model is None or Path(model.GetPathName()).name.lower() != asm.name.lower():
        doc = sw.GetFirstDocument()
        model = None
        while doc is not None:
            if Path(doc.GetPathName()).name.lower() == asm.name.lower():
                model = doc
                break
            doc = doc.GetNext()
        if model is None:
            print(f"opening {asm} ...")
            try:
                errs = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
                warns = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
                model = sw.OpenDoc6(str(asm), swDocASSEMBLY, 1, "", errs, warns)
            except Exception as e:
                print(f"OpenDoc6 failed ({e}); trying OpenDoc")
                model = sw.OpenDoc(str(asm), swDocASSEMBLY)
        if model is None:
            sys.exit("could not open the assembly in SolidWorks")
    try:
        sw.ActivateDoc2(model.GetTitle(), False, 0)
    except Exception:
        pass
    print("document:", model.GetPathName())

    # STL export options
    for pref, val in ((swSTLBinaryFormat, True), (swSTLShowInfoOnSave, False),
                      (swSTLComponentsIntoOneFile, True), (swSTLDontTranslateToPositive, True)):
        try:
            sw.SetUserPreferenceToggle(pref, val)
        except Exception as e:
            print(f"  (toggle {pref} not set: {e})")
    # (STL unit is left as the document's: the sim detects inches / mm / m from the robot's height)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    for old in OUT.parent.glob("*.stl"):
        old.unlink()
    print("exporting ->", OUT)
    ok = model.SaveAs3(str(OUT), 0, 0)
    stls = sorted(OUT.parent.glob("*.stl"))
    if not stls:
        sys.exit(f"SaveAs3 returned {ok} but no STL appeared in {OUT.parent}. "
                 f"Fallback: File > Save As > STL in SolidWorks, see meshes\\README.txt")
    total = sum(p.stat().st_size for p in stls) / 1e6
    print(f"done: {len(stls)} STL file(s), {total:.1f} MB")
    if len(stls) > 1:
        print("  (SolidWorks wrote one STL per component - the sim merges every *.stl in meshes/ automatically)")
    print("Now run 2_RUN_LIVE_VIEWER.bat (or F5 in VS Code): the real CAD is drawn over the blockout.")


if __name__ == "__main__":
    main()
