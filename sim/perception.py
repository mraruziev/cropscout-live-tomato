"""
Perception interface shared by the simulator and your real detector.

Both sources return the same thing: a list of Detection(label, bbox, conf, xyz).
  - detect_ground_truth(): uses MuJoCo's segmentation + depth render (perfect labels, free)
  - detect_with_your_model(): plug your tomato YOLO/CNN in here, same output format

The planner only ever sees Detection objects, so you can swap sources without touching it.
"""
from dataclasses import dataclass
import math

import mujoco
import numpy as np


@dataclass
class Detection:
    label: str                 # "fruit_ripe" | "fruit_unripe" | "leaf_healthy" | "leaf_blight"
    bbox: tuple                # (x0, y0, x1, y1) pixels
    conf: float
    xyz: np.ndarray | None     # world-frame 3D point (from depth), or None
    plant_id: int | None = None


class EyeCamera:
    """Renders RGB, depth and segmentation from a named MuJoCo camera."""

    def __init__(self, gh, cam_name="eye_left", width=480, height=360):
        self.gh, self.cam_name, self.w, self.h = gh, cam_name, width, height
        self.cam_id = gh.model.camera(cam_name).id
        self.renderer = mujoco.Renderer(gh.model, height, width)
        self.opt = gh.scene_option_no_spray()
        fovy = math.radians(gh.model.cam_fovy[self.cam_id])
        self.f = 0.5 * height / math.tan(0.5 * fovy)       # focal length in pixels
        self.cx, self.cy = width / 2.0, height / 2.0

    def rgb(self):
        self.renderer.disable_depth_rendering(); self.renderer.disable_segmentation_rendering()
        self.renderer.update_scene(self.gh.data, camera=self.cam_name, scene_option=self.opt)
        return self.renderer.render().copy()

    def depth(self):
        self.renderer.enable_depth_rendering()
        self.renderer.update_scene(self.gh.data, camera=self.cam_name, scene_option=self.opt)
        out = self.renderer.render().copy()
        self.renderer.disable_depth_rendering()
        return out                                           # metres along the camera axis

    def segmentation(self):
        self.renderer.enable_segmentation_rendering()
        self.renderer.update_scene(self.gh.data, camera=self.cam_name, scene_option=self.opt)
        out = self.renderer.render().copy()
        self.renderer.disable_segmentation_rendering()
        return out[..., 0]                                   # geom id per pixel, -1 = background

    def unproject(self, u, v, z):
        """Pixel (u, v) + depth z (m) -> world xyz. MuJoCo cameras look along -Z with +Y up."""
        x_cam = (u - self.cx) / self.f * z
        y_cam = -(v - self.cy) / self.f * z
        p_cam = np.array([x_cam, y_cam, -z])
        R = self.gh.data.cam_xmat[self.cam_id].reshape(3, 3)
        return self.gh.data.cam_xpos[self.cam_id] + R @ p_cam


def detect_ground_truth(cam: EyeCamera, min_pixels=12):
    """Perfect detections from the segmentation render (one box per fruit / leaf geom)."""
    gh = cam.gh
    seg, depth = cam.segmentation(), cam.depth()
    dets = []
    for gid in np.unique(seg):
        if gid < 0:
            continue
        name = gh.geom_names[int(gid)]
        pid = gh.geom_plant(int(gid))
        if pid is None or not ("_fruit" in name or "_leaf" in name):
            continue
        ys, xs = np.nonzero(seg == gid)
        if len(xs) < min_pixels:
            continue
        x0, y0, x1, y1 = xs.min(), ys.min(), xs.max(), ys.max()
        if "_fruit" in name:
            ripe = gh.model.geom_rgba[int(gid)][0] > 0.6
            label = "fruit_ripe" if ripe else "fruit_unripe"
        else:
            label = "leaf_blight" if "_leafd" in name else "leaf_healthy"   # p{pid}_leafd{i} = diseased leaf
        # 3D point: median depth over the mask, unprojected at the mask centroid
        z = float(np.median(depth[ys, xs]))
        xyz = cam.unproject(float(xs.mean()), float(ys.mean()), z)
        dets.append(Detection(label, (int(x0), int(y0), int(x1), int(y1)), 1.0, xyz, pid))
    return dets


def detect_with_your_model(cam: EyeCamera, model=None):
    """
    Drop-in for the real detector. Sketch for an Ultralytics YOLO model:

        rgb, depth = cam.rgb(), cam.depth()
        results = model.predict(rgb, verbose=False)[0]
        dets = []
        for (x0, y0, x1, y1), conf, cls in zip(results.boxes.xyxy, results.boxes.conf, results.boxes.cls):
            u, v = (x0 + x1) / 2, (y0 + y1) / 2
            z = float(np.median(depth[int(y0):int(y1), int(x0):int(x1)]))
            dets.append(Detection(model.names[int(cls)], (int(x0), int(y0), int(x1), int(y1)),
                                  float(conf), cam.unproject(float(u), float(v), z)))
        return dets

    On the real robot replace `cam.depth()` with the RGB-D camera's depth frame and
    `cam.unproject` with its intrinsics, and the rest of the pipeline is unchanged.
    """
    raise NotImplementedError("wire your tomato detector in here (see docstring)")
