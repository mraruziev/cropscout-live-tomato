EASIEST: double-click 6_EXPORT_CAD_FROM_SOLIDWORKS.bat in the folder above (SolidWorks open) - it does the export below for you.

Drop the SolidWorks export of the robot here as   cropscout_full.stl   and the real CAD skin is drawn
over the blockout robot automatically (nothing else to change).

In SolidWorks, with CropSCOUT_Robot_A08_Raised_Side_Spray.SLDASM open:
  1. File > Save As > file type STL (*.stl) > click Options
  2. Output as: Binary.  Unit: Millimeters.  Resolution: Coarse (Fine makes a huge file).
  3. TICK  "Do not translate STL output data to positive space"   (keeps the CAD origin / ground at Y0)
  4. TICK  "Save all components of an assembly in a single file"
  5. Save as  cropscout_full.stl  in this folder.

If you forget step 3 the sim re-centres the mesh on its bounding box (close enough for a demo).
Axes are converted automatically (SolidWorks Y-up -> MuJoCo Z-up).
