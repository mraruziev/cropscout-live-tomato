# Tomato disease datasets
Each dataset was found by one agent and then fact-checked by a second agent that tried to disprove every claim. Where the two disagree, the **Checked** block wins. The same data is in `data/datasets.json`.

## SLIF-Tomato (Sri Lankan In-Field Tomato Dataset)

- **Link:** https://www.kaggle.com/datasets/romiyalgeorge/slif-tomato-dataset (the URL is correct; Kaggle dataset DOI 10.34740/kaggle/ds/8911633; direct archive endpoint https://www.kaggle.com/api/v1/datasets/download/romiyalgeorge/slif-tomato-dataset). Version 1 was released 2025-12-03. archive.zip is 6.16 GB zipped and 6.62 GB unpacked, with 17,834 files. The download is free. An anonymous GET to the API endpoint returned a 302 redirect to a signed Google Cloud Storage archive.zip URL, so no Kaggle login seems to be needed (I did not fetch the archive). The download button on the website normally asks you to sign in.
- **Used to train the current models:** Yes. The detection part trains the leaf finder; the 890 raw photos (centre squares and finder leaf crops) train the tomato-leaf condition model and the crop/type model ([field-classifier.md](field-classifier.md)).

### Checked

**Task.** Partly true. The archive holds both a classification set and a detection set. I listed the full file tree through Kaggle's public API:
- Raw_Dataset/<class>/ has 890 full-resolution photos with no box files.
- Phase_I-Dataset/<class>/ has 2,670 images and Phase_II-Dataset/<class>/ has 8,934. Both are classification folders.
- Detection_Dataset/images has 2,670 images and Detection_Dataset/lables (misspelled) has 2,670 YOLO .txt label files.

The archive has no data.yaml or classes file, so the mapping from class index to class name is not included and has to be inferred. Bounding boxes exist only for the 2,670 Roboflow-exported Phase-I copies. Those are resized to 640x640, and each raw image appears 3 times (the original plus 2 random augmentations: flip, crop up to 17%, rotation, saturation +/-26%, brightness +/-12%). The raw 890 have no boxes. Per the paper, boxes are drawn on healthy leaves too (Healthy class), not only on diseased regions. Annotation was done in Roboflow. The only task tag on Kaggle is classification.

**Capture.** Mostly confirmed by the Kaggle description and the paper (Neural Computing and Applications 38:554, open access):
- Field capture across the whole 2024 season, January to December.
- Kandy (wet zone), Trincomalee and Jaffna (dry zone), Sri Lanka. Cultivar: Roma tomato.
- Natural light at different times of day.
- Phones: the paper says "five mobile devices" but lists six: Samsung A04s, A30, A72, A10s, Nokia 6.1 Plus and Oppo A37. This is an inconsistency in the paper itself.
- Labels were checked by several pathologists.
- The paper says every image, Healthy included, contains multiple leaves with multiple boxes.

I looked at the Kaggle card image. It shows real field close-ups: several leaves against soil and grass, with natural shadows and some blur. It is not a lab background. However, the frames are close-ups of a leaf cluster, not whole plants, and the paper lists the region of interest as "Leaf". So "whole plants" in the claim is overstated.

**Images.** The totals are confirmed: 890 raw, 2,670 Phase I and 8,934 Phase II. The file counts per folder match exactly.

Per-class raw counts from paper Table 3, which also match the Kaggle folders:

| Class | Raw images | Distinct photo IDs |
|---|---|---|
| Early Blight | 513 | 395 |
| Mosaic | 198 | 120 |
| Wilt | 45 | 21 |
| Healthy | 44 | 44 |
| Late Blight | 34 | 13 |
| Powdery Mildew | 23 | 10 |
| Bacterial Spot | 21 | 6 |
| Septoria | 12 | 5 |

The 890 raw files are not 890 independent scenes. Filenames collapse to 613 base photo IDs (t0001 to t0668), with suffixed siblings such as t0061.jpg (3.9 MB) next to t0061_1 through _4 (about 1.2 MB each). These look like crops or repeat shots of the same scene; I inferred this from names and sizes and did not view them. One ID, t0014, appears in both Early_Blight and Mosaic. Early Blight is 58% of the raw set. I could not confirm the total number of boxes without downloading the label files.

**License.** CC BY 4.0 (Attribution 4.0 International), confirmed by both the Kaggle API metadata and the Croissant metadata. The Kaggle description says users are "required" to cite George R., Thuseethan S., Ragel R.G., Pakeerathan K., Sivalingam V., Mithuran T. (2026), "SLIF-Tomato: Inverted Residual Convolutional Block Attention Module for In-field Tomato Leaf Disease Recognition", Neural Computing and Applications 38(13):554, doi 10.1007/s00521-026-12271-0. The DOI is correct; the paper was first published online on 27 June 2026, is itself CC BY 4.0, and has 0 citations according to Crossref and Semantic Scholar. The Kaggle dataset DOI is 10.34740/kaggle/ds/8911633.

**Commercial use.** Yes. CC BY 4.0 allows commercial use and modification provided attribution is given, which means citing the paper and the dataset and linking the license. Nothing on the page adds a non-commercial restriction. The only extra condition is the citation request, which attribution already covers.

**Usefulness for a live field camera.** Medium. It is genuine in-field phone imagery with YOLO boxes, which is the right domain for live camera detection, and CC BY 4.0 allows commercial use. But it has only about 613 independent scenes, minority classes with 5 to 13 scenes, no class map, and boxes only on augmented copies. Use it to fine-tune or evaluate a detector alongside other data, not as the only training set.

**Errors in the first claim.** 1) "Whole plants" is wrong. The images are close-ups of several leaves, and the paper's region of interest is "Leaf".

2) "Per-class counts could not be confirmed" is wrong. Paper Table 3 gives them: Early Blight 513, Mosaic 198, Wilt 45, Healthy 44, Late Blight 34, Powdery Mildew 23, Bacterial Spot 21, Septoria 12. Box totals remain unconfirmed.

3) "Train and evaluate on the raw 890 only" cannot be done for detection. The raw 890 have no boxes; boxes exist only on the 2,670 augmented 640x640 Roboflow copies. Splits must be made by source group: strip the ".rf.<hash>" suffix and better still group by base ID tNNNN, because the _1/_2 siblings appear to come from the same scene. In practice there are only about 613 independent scenes, and some classes have very few (Septoria 5, Bacterial Spot 6, Powdery Mildew 10, Late Blight 13).

4) The paper's own results are probably inflated by leakage. Detection used the Phase-I augmented set split randomly 70/20/10. The reported 88.5% precision, 80.1 mAP@50 and 57.2 mAP@50:95 for YOLOv12l are therefore likely optimistic. The 99.66% and 99.91% classification results come from 5-fold cross-validation on the augmented Phase I and Phase II sets and are similarly suspect.

5) The archive has no class-map or data.yaml file, so YOLO class indices have to be inferred.

6) "Boxes per diseased region": the Healthy class is boxed too.

7) The paper says five phones but lists six.

8) The Kaggle task tag is classification only.

9) Minor: the dataset went up on Kaggle in December 2025 and has about 3,400 downloads, so "new" is relative. Usability 0.6875 (6.88) and "uncited" (0 citations) are correct.

Process note: WebFetch cached the open-access paper PDF and the Kaggle card image under ~/.claude/projects/.../tool-results automatically. I wrote nothing else outside the scratchpad and touched nothing under the CropSCOUT work folder.

### First claim

- Why relevant: This is the closest public match to what a phone camera sees in a field: whole plants with several leaves, phone sensors, varied light and time of day, boxes per diseased region, and labels checked by plant pathologists. It also adds Powdery Mildew and Wilt, which CropSCOUT does not have.
- Caveats: Small (890 unique photos). Train and evaluate on the raw 890 only, because the augmented copies leak across splits if they are re-split. Per-class counts and box totals could not be confirmed. Single region (Sri Lanka). 'Wilt' and 'Mosaic' are whole-plant syndromes, not leaf lesions. Kaggle usability is low (6.88) and the release is new and uncited, so check box quality first.

## Tomato Disease Dataset (Sichuan greenhouse; Liu et al., Data in Brief 2025)

- **Link:** https://data.mendeley.com/datasets/c2x8rynybg/1 (correct as given; DOI 10.17632/c2x8rynybg.1, version 1 published 2025-07-22). Paper: Liu Y, Zhu Y, Hu L, Huo Y, Gao W, Hu R, He P, 'A labeled image dataset of common tomato diseases for classification and object detection', Data in Brief 63 (2025) 112032, doi:10.1016/j.dib.2025.112032, PMC12553018. The Mendeley page lists only Yongbo Liu as contributor. Download is free and needs no login: with no auth, the Mendeley public API returns a whole-dataset zip redirect (public-api/zip/c2x8rynybg/download/1 -> S3 presigned c2x8rynybg-1.zip) and gives a public download_url for each file. I only listed the files and looked at a few XML files; I did not do a full download.
- **Used to train the current models:** Yes. The leaf, fruit and stem boxes train the leaf finder; the `Viral` photos train the tomato-leaf condition model as mosaic virus, leaf crops only where they match a `Viral_Leaf` box ([field-classifier.md](field-classifier.md)).

### Checked

**Task.** CONFIRMED: object detection. Pascal VOC XML from LabelImg, one XML per image (the <path> field shows E:\Dataset\images\..., which is LabelImg output), with <bndbox> boxes and no segmentation. The paper defines 18 label names: {Viral,GrayMold,Wilt}_{Leaf,Fruit,Stem,Top,Middle,Base}. Labels I saw in the actual XML files: GrayMold_Fruit, GrayMold_Leaf, Viral_Leaf, Wilt_Leaf, Wilt_Stem, Wilt_Middle, Wilt_Base, so the organ and vertical-zone labels are both real. The XML uses 'Viral_Leaf'; the paper's table misspells it 'Viral_leaf'. I did not check that all 18 names occur. The box count is not stated anywhere. From annotation byte sizes (about 235 bytes per object), I estimate roughly 3,100 boxes: about 1,640 viral, 1,335 wilt, 128 gray mold. Viral images in my sample were almost all Viral_Leaf, so few boxes are likely to be fruit or stem.

**Capture.** Mostly CONFIRMED, with one error. The paper states iPhone 14, natural light only (9:00-16:00, no artificial lighting), 0.2-2.0 m from close-up to whole plant, May-Nov 2024, Sichuan, China. Image files are 4032x3024 or 3024x4032 JPG; the paper's '3024 x 4023' is a typo. File names carry MMDD date codes, which show only 5 capture days: 0509, 0617, 0919, 1021, 1112. ERROR in the claim: the site is the 'Modern Agricultural Science and Technology Innovation Demonstration Park, Sichuan Academy of Agricultural Sciences', a research/demonstration park run by an academy, not a 'commercial greenhouse'. Paper coordinates are 30.7797 N, 104.2082 E; section 4.1 swaps them, as the claim says.

**Images.** CONFIRMED: 1,026 images, counted file by file through the Mendeley API: GrayMold 82, Viral 417, Wilt 527, with exactly matching XML counts. The paper gives about 175 plants (viral ~80, gray mold ~15, wilt ~80). Images total about 2.99 GB (2.78 GiB, the paper's '2.78 GB'); the Mendeley description says 3.14 GB. There is no healthy class. Distribution by capture date, which the claim does not mention: Gray mold only on 0509 (69) and 0617 (13); Viral on 0617/0919/1021/1112 (17/115/112/173); Wilt on 0919/1021/1112 (49/175/303). Class is confounded with date and season.

**License.** Dataset: CC BY 4.0 (Creative Commons Attribution 4.0 International), from the Mendeley API data_licence field and the dataset page. Article: open access CC BY-NC according to PMC; I did not confirm the exact version ('4.0'). The NC applies to the paper text and figures only, not to the dataset.

**Commercial use.** yes: the dataset is CC BY 4.0, which allows commercial use with attribution (credit Liu et al. and the Mendeley DOI, link the license, note any changes). Do not reuse figures or text from the CC BY-NC paper on the commercial site. The Mendeley terms add a third-party content caveat, but nothing in the dataset is marked as third-party.

**Usefulness for a live field camera.** medium: these are real phone-camera greenhouse shots at live-view distances, with organ boxes, and the license allows commercial use. Against that: only 3 coarse classes, no healthy class, 82 gray mold images, about 175 plants over 5 dates with class confounded by date, mostly leaf boxes, and Top/Middle/Base zone boxes that are too coarse for a lesion detector. Use it as a supplement, not the main training set.

**Errors in the first claim.** 1) 'Commercial greenhouse' is wrong: it is a demonstration park run by the Sichuan Academy of Agricultural Sciences. 2) The paper's license is listed as 'CC BY-NC 4.0'; PMC shows CC BY-NC, and I did not verify the 4.0. 3) 'Box count not stated' is accurate; my estimate is about 3,100. 4) The claim leaves out a serious caveat: only 5 capture dates, and class is confounded with date (gray mold May/June only, wilt Sep-Nov only), so a model can learn season or plant stage instead of disease. Split by date and plant, and expect weaker per-class results than reported. 5) Minor documentation problems the claim does not mention: the paper says resolution is 3024x4023 (it is actually 4032x3024), writes 'Viral_leaf' where the files use 'Viral_Leaf', and gives size as 2.78 GB vs 3.14 GB on Mendeley. Everything else in the claim checks out: 1,026 images (417/82/527), about 175 plants, iPhone 14, natural light, 0.2-2.0 m, May-Nov 2024, Pascal VOC from LabelImg, 18 labels including Top/Middle/Base, CC BY 4.0, swapped coordinates in one section, no healthy class.

### First claim

- Why relevant: Taken with a phone at the same distances a user would hold one in a live view, from organ close-ups out to whole plants. It boxes fruit and stems as well as leaves, which makes it one of the few sources of diseased tomato fruit on the plant. Gray mold and bacterial wilt are new classes for CropSCOUT.
- Caveats: Only 3 diseases and no healthy class. Gray mold has just 82 images. About 175 plants means many near-duplicate views, so split by plant and capture day. 'Viral' is a coarse label with no virus named. One greenhouse in one season. Coordinates are reversed in one section of the paper.

## Tomato-Village (Gehlot et al., Multimedia Systems 2023)

- **Link:** https://github.com/mamta-joshi-gehlot/Tomato-Village (the URL is correct). The paper is Gehlot, Saxena & Gandhi, Multimedia Systems 29:3305-3328 (2023), doi:10.1007/s00530-023-01158-y. The paper is closed access. The repo is public and free, with no login needed. The GitHub API counts 53,289 files totalling about 4.0 GB. The images are plain git blobs, not LFS. The last push was 2024-05-13. No mirror on Kaggle, Roboflow or Hugging Face was found.
- **Used to train the current models:** No

### Checked

**Task.** Confirmed, and the repo tree and paper add detail. Variant-a is single-label classification in folders: 8 classes, train/val/test. Variant-b is multi-label classification via one CSV ('Multi-Label dataset - with augmented.csv', 8 one-hot columns). It has 5,653 rows: 4,525 single-label (the Variant-a images again), 1,106 with two labels and 22 with three, mostly Leaf Miner plus Mg deficiency or SWV. Variant-c is object detection with 8 classes, train/val only (no test split). Each image has a YOLO .txt and a Pascal VOC .xml, and the class map is in 'Varient-C Labels.txt'. Small quirk: the YOLO class ids are written as floats ('6.0 0.58 ...').

**Capture.** Only partly true. The claim calls all of it field capture, which is wrong for Variant-a and Variant-b. The paper says those leaves were plucked from a Jodhpur field, placed one at a time on white paper, and photographed. A sample I viewed is a 256x256 single detached leaf on white paper, so these are curated studio-style images, not in-situ. Only Variant-c is in-situ; the paper says those were captured directly in the field. Variant-c images are 640x640, resized from 3:4 phone photos. Its 1,796 source photos split by filename into three groups. 629 are 'Jaipur_Pots': a sample shows a plant in a red pot. 82 are 'Jodhpur_Land': open ground, as claimed. The largest group, 1,085 (60%), are 'IMG202203xx' phone files from 23-25 Mar 2022 with no location in the name; a sample shows sandy open-field soil. So "Jodhpur land plus Jaipur pots" leaves out most of Variant-c. The paper mentions three locations (1 Jodhpur, 2 Jaipur) and never uses the word 'pot'. The 2025 Data in Brief paper (Liu et al., vol 63, 112032) does say Tomato-Village "was not collected under natural conditions", which fits the white-paper variants.

**Images.** Variant-a has 4,525 JPGs, not 4,526: train 3,162 / val 902 / test 461. The claim's extra train item is a desktop.ini file. They come from 2,103 unique source photos (matching the paper's 2,103 originals); 2,422 are _1 to _7 augmented copies of 346 source photos. Per class: Leaf Miner 1,024, Mg 937, Late blight 904, SWV 517, Early blight 496, N 360, Healthy 216, K 72. The 72 potassium images come from only 9 unique leaves. Variant-b has 5,653 JPGs (train 3,945 / val 1,124 / test 584) and is a superset of Variant-a. Variant-c has 14,368 JPGs (train 11,493 / val 2,875), which is 1,796 unique sources x 8 (original plus _aug1 to _aug7). All 1,484 val sources also appear in train, confirmed by exact filename match. I sampled 90 original YOLO files (1,275 boxes): about 87% Leaf Miner, few Late blight or Mg/N/K, some SWV, and no Early_blight or Healthy boxes. Variant-c is very imbalanced. The paper reports 21,129 boxes before augmentation.

**License.** There is no license. There is no LICENSE file, GitHub's license field is null, and /repos/.../license returns 404. The README has no terms of use, only a citation request. The paper is closed access under Springer's text-and-data-mining license, not Creative Commons. Default copyright (all rights reserved) applies.

**Commercial use.** no. No license grants any reuse right. Using it on commercial CropSCOUT would need written permission from the authors (Mamta Gehlot et al.). Until then it is limited to private evaluation at most, and even that has no explicit grant.

**Usefulness for a live field camera.** medium. Variant-c is in-situ multi-box detection, which is the right shape for a live camera, but it is small (1,796 photos at 640x640, squashed), about 87% Leaf Miner, and leaky. Variant-a/b (white-paper leaves) are of little use for live video, and the lack of a license blocks commercial use.

**Errors in the first claim.** 1) The image count is off by one: Variant-a has 4,525 images, train 3,162, not 4,526 / 3,163; the extra item is desktop.ini. 2) The capture description is wrong for Variant-a/b: they are detached leaves on white paper, not field images. Only Variant-c is in-situ. 3) The filename-based capture summary leaves out 1,085 of Variant-c's 1,796 sources (60%), whose IMG2022* names carry no location. 4) The claim omits Variant-b's size: 5,653 images, a superset of Variant-a. 5) The leakage caveat is incomplete. Variant-a leaks too: 327 of 346 augmented source photos have copies in more than one of train, val and test. That inflates its reported scores as well. 6) "Potassium about 72 images" is true but misleading: there are only 9 unique leaves. 7) The claim doesn't mention that Variant-c is dominated by Leaf Miner (about 87% of sampled boxes, with Early blight and Healthy almost absent). 8) "Tuta absoluta-type damage" is not stated by the source; the paper just says "Leaf Miner". 9) The license point is correct and is indeed the main blocker. 10) "Pot-grown Jaipur images are a large share" holds only for Variant-c (35% of sources) and not for Variant-a. Checks used the GitHub git-tree API (full, not truncated), the Springer article page, the Data in Brief PMC article, and three Variant-c sample images plus one Variant-a image viewed in a browser. Nothing was downloaded to the user's folders.

### First claim

- Why relevant: It ships ready-made detection boxes on in-situ plants. Leaf Miner (Tuta absoluta-type damage), Spotted Wilt Virus and nutrient-deficiency classes cover common field look-alikes that a live scanner would otherwise mislabel as disease.
- Caveats: Severe leakage. All 1,484 source photos behind the Variant-c val split also appear in train as augmented copies (verified from filenames), so published scores are inflated. Re-split by source photo. Potassium Deficiency has only about 72 images. A 2025 review says it was not collected under natural conditions; pot-grown Jaipur images are a large share. The license problem is the main blocker.

## PlantDoc (object-detection and classification versions)

- **Link:** Both URLs are correct and live. Detection: https://github.com/pratikkayal/PlantDoc-Object-Detection-Dataset. Classification: https://github.com/pratikkayal/PlantDoc-Dataset. Both are public, free, and need no login (git clone or ZIP). The GitHub API reports about 0.96 GB for each repo. Paper: https://arxiv.org/abs/1911.10317 (DOI 10.1145/3371158.3371196). The classification README calls its contents "Cropped-PlantDoc", but the repo actually holds full, uncropped images. The real 9,216-crop C-PD set described in the paper is not in it.
- **Used to train the current models:** Yes. The detection boxes are mapped in the data-preparation script (PLANTDOC_MAP; spider mites skipped). plantdoc gives 3,544 rows in the crop/type training data and 3,514 in the condition training data, counted across all crops.

### Checked

**Task.** Confirmed. The detection repo has TRAIN/ and TEST/ folders with 2,593 Pascal-VOC XML files (one I checked has the usual <annotation><object><bndbox> structure). It also has train_labels.csv and test_labels.csv with the columns filename,width,height,class,xmin,ymin,xmax,ymax (8,469 + 452 box rows). The classification repo is train/ and test/ with one folder per class, 28 class folders in each. The caveat is that its images are the same full images as the detection repo (all 746 tomato files are byte-identical by git SHA), not leaf crops. The two "versions" therefore share one image pool and give no extra data. CropSCOUT's local copy  is a YOLO-format conversion with data.yaml, labels/*.txt, 2,338 train and 236 val images, and the same 29 class names.

**Capture.** Mostly confirmed, with nuance. The paper says the images were scraped from Google Images and Ecosia, and that "lab controlled" images were removed. The FieldPlant authors (IEEE Access 2023) still say PlantDoc includes some laboratory images. In a random sample of 10 tomato images I viewed, 7 were plants in situ (garden, field canopy, greenhouse, against a wall), 2 were detached leaves on plain studio backgrounds (cream and black), and 1 was a close-up macro. One showed a "University of Maryland Extension" watermark. Some filenames point to non-photo sources, such as "tylcv-seminar-1-638.jpg" (a slide) and Alamy stock IDs. So "mixed, mostly in-situ plus some lab-style images" is a fair description.

**Images.** Confirmed exactly. From the detection CSVs: 746 tomato (split, image) pairs (677 train + 69 test) and 2,932 tomato boxes (2,740 train + 192 test). From the classification folders: 677 train + 69 test = 746. The 9 tomato classes match the claim. Spider mites has 2 images and 2 boxes (both train, none in test). By box count: Septoria 436, healthy 396, bacterial spot 280, early blight 214, late blight 221, mosaic 261, yellow leaf curl 829, leaf mold 293. Only 743 tomato filenames are unique, because 3 appear in both train and test: tomato_V8.jpg, tylcv-seminar-1-638.jpg and early-blight-septoria-ls-fig-3.jpg. Image sizes: median long side 700 px, 10th percentile 319 px, 90th percentile 1,989 px. 237 of 743 are 500 px or smaller.

**License.** CC BY 4.0, confirmed. The GitHub API reports spdx CC-BY-4.0 for both repos. Both LICENSE.txt files are the full "Attribution 4.0 International" text with no ShareAlike or NonCommercial terms, and both READMEs say "Creative Commons Attribution 4.0 International". The CropSCOUT inconsistency is real. In vision/private/dataset-provenance.json, sources.plantdoc.license is "CC BY-SA 4.0", while every datasets.*.source_licenses.plantdoc is "CC BY 4.0". The wrong value comes from the provenance build script (now fixed). the data-preparation script correctly says CC BY 4.0.

**Commercial use.** Unclear. The CC BY 4.0 license itself allows commercial use with attribution. But the images were scraped from the web (Google Images and Ecosia), and the paper says nothing about copyright or permissions. Some images carry third-party watermarks (University of Maryland Extension) or have stock-photo filenames (Alamy IDs such as AXK6AY), so the authors could not have licensed those pixels under CC BY. The annotations and compilation are clearly CC BY. Rights in the underlying photos are not, so redistributing the images or relying on them commercially carries risk.

**Usefulness for a live field camera.** low: CropSCOUT already uses all 746 noisy web stills, so for live camera they add no new data and are not a clean held-out test.

**Errors in the first claim.** 1) The claim's suggestion to keep PlantDoc as a held-out field test does not work as stated. CropSCOUT already trains on its train split (the data-preparation script _add_plantdoc reads both train and val). The local val split is the 236-image TEST split, already used for validation and model selection. Also, 16 detection filenames (3 of them tomato) appear in both TRAIN and TEST, and the classification repo has 11 byte-identical train/test duplicates. It is not a clean held-out set unless the model is retrained without it and the duplicates are removed. 2) Detection and classification are listed as two sources, but they are the same 746 tomato images. The classification README's "Cropped-PlantDoc" label is wrong for what the repo contains. 3) The claim about Roboflow forks could only be partly checked. Search snippets confirm "Tomato Leaf Disease" projects with 739 images each under Roboflow accounts Test 2, 4, 6 and 7 (Test 5 also appeared in one result list). The pages returned 403, so "several dozen" and "copies of this subset" are unverified, though 739 is close to the 743 unique tomato filenames. 4) Minor: the paper says 2,598 images and 9,216 boxes and that classes under 50 images were dropped. The repo's CSVs actually hold 2,581 labelled images and 8,921 boxes, and the spider-mites class has only 2 images. 5) More label-noise evidence supports the caveat: 5 images with "tomato" early blight in their filenames sit in the Potato early blight folder, and one sampled image labelled Septoria looked like a healthy leaf. The FieldPlant critique ("absence of plant pathologists") is confirmed, and the PlantDoc paper itself admits a "lack of extensive domain expertise". 6) The CropSCOUT counts are confirmed: plantdoc gives 3,544 in the crop/type data and 3,514 in the condition data source_counts_all_splits. Note that the condition rows cover only apple and tomato, so "across all crops" really applies only to identity. The PLANTDOC_MAP and spider-mite skip (PLANTDOC_SKIP) are confirmed at lines 205-220.

### First claim

- Why relevant: It is still the standard in-the-wild benchmark, and its boxes let a detector learn to find leaves in cluttered frames. CropSCOUT already uses it, so it is better kept as a held-out field test than as a source of new data.
- Caveats: Label noise is well known (it was annotated without pathologists, as the FieldPlant authors point out). Images are small web images with watermarks and possible copyright problems upstream. Several dozen Roboflow forks ('Tomato Leaf Disease' by Test 1-10, 739 images each) are copies of this subset, so do not ingest them as new data.

## Tomato Leaf Disease (Universitas Atma Jaya), the largest Roboflow Universe tomato detection set

- **Link:** https://universe.roboflow.com/universitas-atma-jaya/tomato-leaf-disease-rxcft (URL is correct. The page blocks plain curl and WebFetch behind a Cloudflare challenge, but it loads in a real browser. Downloading is free but needs a login: /dataset/6/download shows "Login or create a free account". Anonymous visitors can only preview 50 images per query, and the page says "Sign in to browse all 8,439 images".)
- **Used to train the current models:** No

### Checked

**Task.** Confirmed. The page says "Task: Object Detection" and the images carry bounding boxes. But many boxes are effectively classification labels: the PlantVillage-style single leaves (Bacterial Spot "Bs*.JPG", "___GCREC_Bact-Sp", "Yellow Leaf Curl Virus (n).JPG") have one box covering almost the whole leaf or frame. The hosted model is v3 (tomato-leaf-disease-rxcft/3). Roboflow's blog reports 68.1% mAP for it.

**Capture.** REFUTED as worded ("mostly on-plant field/greenhouse with dark backgrounds"). I checked the 50 newest images per class filter (the anonymous limit). The set is a mix of very different sources, and I cannot estimate the share of each from these samples. (1) On-plant phone and camera photos that look like the authors' own: IMG20221006*, IMG_20221001*, IMG_20221231*, DSC035xx. They dominate Early Blight and Leaf_Miner. (2) Roboflow-edited "-transformed" copies, often on-plant with dark backgrounds, in Spider Mites and YLCV. (3) PlantVillage lab images: single detached leaves on a grey board. Filenames include "uuid___GCREC_Bact-Sp", "___PSU_CG" (Mosaic) and "___UF-GRC_BS_Lab Leaf", and "Yellow Leaf Curl Virus (n).JPG" looks the same. (4) Web-scraped images. Spider-mites-fig-11.jpg is confirmed. The 50 newest Late Blight images are almost all POTATO late blight, for example "Late+blight+on+potato.jpg", "wur-late-blight-in-potato-809.jpg", "B2650062-Potato_late_blight-SPL.jpg" and "potato_late-blight_08_zoom.jpg". I opened one: a potato leaf boxed as "Late Blight". Early Blight also has potato images ("potato_early-blight_06_zoom.jpg", "B2650214-Potato_leaf_blight-SPL.jpg"). Other non-tomato images: Mosaic has "tobacco-mosaic-virus-eggplant-*.jpg", Septoria has "septoria+on+rudbeckia.jpg", and Healthy/Leaf_Miner has "stock-photo-leaf-miner-larva-disease-in-yardlong-bean-leaves-*". (5) Screenshots from YouTube-style videos with text overlays, such as "Screenshot (110).png" showing "Leaf miner" and "HOW TO USE NEEM OIL SPRAY". (6) Leaf Mold is almost entirely serial-coded "V006_77_1_18_11_03_13_*_2020*.jpg" images of unknown, undocumented origin. (7) Iron Deficiency shows plants against a grey backdrop, not a dark real background.

**Images.** 8,439 images are on the project page, but NOT all are tomato: there are confirmed potato, eggplant, rudbeckia and yardlong-bean images. v3 (2023-02-27) shows 19,430: train 17,235, valid 1,584, test 611, stretched to 640x640, with 3 outputs per training image (flip H/V, ±45° rotation, ±25% saturation, ±25% exposure). Working backwards, that is only about 7,940 source images, not 8,439. v6 (2023-04-01) shows "41366" total, but its splits add up to 20,683 (18,366 / 1,679 / 638, shown as 44%/4%/2%, which totals 50%). So 41,366 looks like a double-count on the page. 18,366/3 + 1,679 + 638 = 8,439 exactly. v6 is stretched to 512x512, uses different augmentations (90° rotations, ±15° rotation, ±15° shear, ±5% exposure), and has "Modify Classes: 1 dropped", so it has 10 classes, not 11. All 11 classes are listed correctly on the page. Iron Deficiency is tiny: its class filter returned only 12 images (other classes hit the 50 cap). Bryan 4.13k, Hung Nguyen 4.12k, Personal 4.45k, Test 8 5.99k, TEST 8.91k and Test 10 9.41k all exist in Universe search. Whether they are forks of this set is not shown.

**License.** The page declares CC BY 4.0. The citation says Universitas Atma Jaya, 2023, April. The declaration is not trustworthy for much of the content. It includes stock and agency images (SPL "B2650062-...-SPL.jpg"; Alamy-style IDs "...-B7G2EC_jpg_rf_..."; iStock "picture-id128110611"; Shutterstock-style "stock-photo-...-1651087195"), an Elsevier book figure ("3-s2-0-B978012802441600005X-f05-02-9780128024416.jpg"), extension-service and blog images, video screenshots, and PlantVillage images. The uploader could not have relicensed any of these under CC BY 4.0. The "V006_*" Leaf Mold images have no documented source or license.

**Commercial use.** unclear, leaning no. CC BY 4.0 would normally allow commercial use with attribution. But the uploader clearly did not own large parts of the set (stock agency, publisher, video and PlantVillage images), so the CC BY 4.0 label does not cover them. Using the set as-is in commercial CropSCOUT would carry infringement risk. At most, a hand-curated subset of the authors' own field photos (IMG2022*, DSC035xx) could be considered, and even their provenance is undocumented.

**Usefulness for a live field camera.** low. Some on-plant tomato images have multiple boxes per image, which is what a live camera needs, but they are mixed with potato and other non-tomato images, lab-leaf PlantVillage images with whole-frame boxes, and video screenshots with text overlays, and the commercial license is unclear. It could only be used as a heavily hand-curated subset and checked against CropSCOUT's own field photos.

**Errors in the first claim.** 1) Calling it "the largest Roboflow Universe tomato detection set" is false. By image count, Test 10 (9.41k), ttianyuu (9.24k), TEST (8.91k) and student (8.64k) are all larger. 2) "Mostly on-plant field/greenhouse with dark backgrounds" is not supported. There is a large share of PlantVillage lab leaves on grey boards, plus web, stock and book images and video screenshots, and the Late Blight sample is mostly POTATO. 3) "8,439 tomato images" is wrong: potato, eggplant, rudbeckia and yardlong-bean images are included. 4) v6 "41,366" is a display artifact. Its splits add up to 20,683, and v6 dropped one class. v3's 19,430 comes from about 7,940 sources, not 8,439. 5) "Download the un-augmented source images" is not directly possible. The only public versions are v3 and v6, both with 3x train augmentation. You would have to fork the set with a free account and generate a version without augmentation. Many "-transformed" files are already edited duplicates inside the source set. 6) "Adds Iron Deficiency" is near-meaningless: only about 12 images. 7) Download requires a (free) Roboflow login. 8) The overlap goes beyond what the claim says: PlantDoc/Test-N style files ("Tomato-Septoria-leaf-spot-(118)-transformed.jpeg", "Tomato-leaf-yellow-virus-(38)-...") and PlantVillage files sit inside this set itself, not only in the forks. These numbers check out: 24 stars, 28.7k views, 1.13k downloads, 11 classes, last update 2023 (versions Feb and Apr 2023). "Most-used" across all of Universe was not verified.

### First claim

- Why relevant: This is the most-used Roboflow tomato detection set (24 stars, 28.7k views, 1.13k downloads). It has the most boxed images of tomato leaves on the plant and adds Leaf Miner, Spider Mites and Iron Deficiency.
- Caveats: Download the un-augmented source images, not the v3 or v6 exports. Many forks re-upload it (Bryan 4.13k, Hung Nguyen 4.12k, Personal 4.45k, Test 8 5.99k, TEST 8.91k, Test 10 9.41k), so dedupe with perceptual hashing before mixing sources. It probably overlaps with PlantDoc and other web images; Test 8 explicitly merges PlantDoc class names. No collection protocol or pathologist review is documented, so label noise is unknown. Last updated in 2023.

## Tomato Leaf Dataset v2: multiclass disease detection and classification (Bangladesh)

- **Link:** https://data.mendeley.com/datasets/bpfd9cns5g/2 is correct (DOI 10.17632/bpfd9cns5g.2, published 4 Mar 2025; v1 is from 5 Sep 2024). The exact title is "Tomato Leaf Dataset : A dataset for multiclass disease detection and classification", by Imtiaz, Islam Swapnil, Masud and Karmaker at AIUB. The companion paper is Data in Brief 2025, DOI 10.1016/j.dib.2025.111520 (https://pmc.ncbi.nlm.nih.gov/articles/PMC12008584/). No login is needed: the public zip endpoint (data.mendeley.com/public-api/zip/bpfd9cns5g/download/2) returned HTTP 200, a ~49 MB zip, and single files download without auth too.
- **Used to train the current models:** Yes. This is the 'tomato_leaf' source (DOI 10.17632/bpfd9cns5g.2): 474 rows in the crop/type training data and 1,860 in the condition training data (box crops). It is the only source of Tomato_leaf_black_spot and most of Tomato_leaf_target_spot.

### Checked

**Task.** Object detection: partly confirmed. Classification: not supported as shipped. The "Annotated" folder holds train 597 / valid 61 / test 31 images with YOLO-style TXT files. All 2,278 label lines have 5 columns (class cx cy w h), so they are boxes, not polygons; the paper says Roboflow made them. There is no data.yaml or classes file in v1 or v2 (the Mendeley file API lists only .jpg and .txt), so class IDs 0-6 have no names in the data. The paper says the raw data sits in per-class folders, but the Raw Data folder on Mendeley is one flat "images" folder with no labels. Any class label, image-level or box-level, therefore depends on guessing the ID-to-name mapping.

**Capture.** Locations: confirmed from text. The Mendeley page and the paper both say tomato gardens in Dinajpur, Thakurgaon and Kushtia, and "Over seven days". Camera: only in the paper ("Canon EOS M50 high-resolution camera"), not on the Mendeley page. The files cannot confirm it because every image checked has its EXIF stripped and is 640x640, including the "Raw Data" set. Those files carry Roboflow ".rf.<hash>" names, so they are Roboflow exports, not camera originals. The paper says the images were resized to 640x640; it does not say whether that was a stretch or a crop. I could not look at the images to confirm field conditions, because browser navigation to data.mendeley.com was denied. "Field" therefore rests on the authors' text only.

**Images.** 731 is a file count, not 731 distinct photos. The 731 files in Raw Data come from only 302 unique camera photos (IMG_0210 to IMG_1150): 213 photos appear 3 times, 3 appear twice and 86 once. I compared copies in memory and they are near-identical (mean grey difference about 0.2-0.7 versus about 30 for unrelated photos), and 14 copies are byte-identical. The Annotated set has 689 files from 308 unique photos. Its train split holds 216 photos with up to 3 copies each, rotated 90 degrees with boxes rotated to match. Splits do not overlap by photo. Version 1 also had an "Annotated & Augmented" folder of 639+62+30 = 731 files. The label files contain 2,278 boxes; counting one copy per photo gives 1,027 boxes. By class ID: 0=84, 1=1177, 2=179, 3=303, 4=93, 5=47, 6=395 (deduplicated: 34/529/80/146/42/23/173). 19 label files are empty. Neither 1,621 nor the per-class Table 1 counts (325/254/202/194/233/213/200) match the shipped files under any ID ordering.

**License.** CC BY 4.0 (Creative Commons Attribution 4.0 International), from the Mendeley API data_licence for both v1 and v2. The Data in Brief article is also CC BY 4.0.

**Commercial use.** unclear. The CC BY 4.0 licence allows commercial use with attribution. However, the paper's Ethics Statement says the aim was "not for commercial exploitation" and that the data is intended for research only. That statement is not a licence term, but it conflicts with the licence. Since CropSCOUT is commercial, get written confirmation from the authors (AIUB, contact Ahmed Imtiaz) before relying on it in a commercial model.

**Usefulness for a live field camera.** low. It has only about 300 unique 640x640 photos from one week, and the class IDs have no names. CropSCOUT's current ID mapping looks wrong (for example, it labels lesion-sized boxes as "healthy"). It is already in the build. Its tiny lesion boxes could only help a lesion localiser after someone checks the class IDs by eye.

**Errors in the first claim.** 1) "731 images" is wrong as a count of distinct photos. There are about 302 unique raw photos and 308 annotated photos; the rest are Roboflow copies. 2) "1,621 box annotations" with the per-class split comes from the Mendeley text and paper Table 1. The shipped files contain 2,278 boxes (1,027 without copies), and the class distribution is very different. 3) The claim implies the classes are known. In fact no class-name file is shipped, so the ID-to-name mapping cannot be checked. CropSCOUT's the data-preparation script TOMATO_CLASS_MAP assumes paper Table 1 order (0 early_blight, 1 black_spot, 2 late_blight, 3 leaf_mold, 4 bacterial_spot, 5 target_spot, 6 healthy). The box statistics argue against that. ID 6 ("healthy" in CropSCOUT) is tiny lesion-sized boxes: median 0.06% of the image (about 15x15 px), up to 9 per image, appearing with ID 1 in 159 images. ID 2 ("late_blight" in CropSCOUT) is always exactly one box per image covering most of the leaf (median 64% of the image) and never appears with any other class. Roboflow's usual alphabetical ordering would give 0 Bacterial Spot, 1 Black Spot, 2 Early Blight, 3 Healthy, 4 Late Blight, 5 Leaf Mold, 6 Target Spot. Under that mapping, CropSCOUT's healthy, target_spot, early_blight, late_blight, leaf_mold and bacterial_spot crops from this source would all be mislabelled; only black_spot (ID 1) agrees. The CropSCOUT row counts are accurate (474 crop/type rows; 1,860 condition rows; black_spot 790+162). 4) The camera (Canon EOS M50) is from the paper only and cannot be checked from the files. 5) "Classification" is not supported as shipped, because the raw folder has no class folders, despite what the paper says. 6) Minor: the paper says "Debajyoti", Mendeley says "Debajoyti", and the paper calls three subfolders "Two subfolders". The claim's caveats that are correct: small, one week, 640x640, black_spot_unresolved appears in cropscout_sources.yaml, and you should split by image. Splitting should go further, by photo base name, because of the rotated copies.

### First claim

- Why relevant: Field photos with boxes. It is already in the build, so its marginal value is low. Its boxes can be reused to train a leaf or lesion localiser for the live pipeline.
- Caveats: Very small, from one week and one camera. Images are resized to 640x640. 'Black Spot' (Alternaria) overlaps visually with Early Blight; CropSCOUT's own cropscout_sources.yaml calls it 'black_spot_unresolved', so consider merging the two. Split by image, not by crop, to avoid leakage.

## CCMT: Dataset for Crop Pest and Disease Detection (Ghana; tomato subset)

- **Link:** https://data.mendeley.com/datasets/bwh3zbpkpv/1 is the correct URL (DOI 10.17632/bwh3zbpkpv.1, published 26 Apr 2023, v1 only). The companion paper is Data in Brief 2023, doi:10.1016/j.dib.2023.109306 (PMC10285554). The data is free and needs no login. With HEAD requests only, I confirmed that each file's public URL redirects to a public S3 object (HTTP 200) and that the "Download All" zip redirects to a presigned S3 URL. Neither needs auth. The whole release is 130,472 JPEGs, 8,424,664,368 bytes (shown as "Download All 7.86 GB"). There is no tomato-only zip. The raw tomato folder alone is about 284 MB (5,805 files), and each file has its own public URL, so a script can fetch just those. I did not download any images.
- **Used to train the current models:** Yes: the raw `healthy` and `septoria leaf spot` folders, deduplicated by SHA-256 and perceptual hash and split by photo group, in the tomato-leaf condition model and the crop/type model ([field-classifier.md](field-classifier.md)). Leaf blight, leaf curl and verticillium wilt have no matching class and are not used.

### Checked

**Task.** Classification only, confirmed. Every one of the 130,472 files is image/jpeg, sorted into one folder per class (Raw Data/CCMT Dataset/Tomato/<class>, and CCMT Dataset-Augmented/Tomato/{train_set,test_set}/<class>). The release has no XML, JSON, CSV or txt annotations, so there are no boxes or masks. The paper's "annotation" step means expert class labelling: two experts cross-checked each label and images without agreement were dropped.

**Capture.** Mixed, as claimed, and the tomato images appear to be mostly in-field shots of leaves on the plant. The Mendeley "Steps to reproduce" text says images were "captured under various conditions and with different backgrounds such as white, dark, illuminated, and real backgrounds", taken on local farms in Ghana. Per the paper, capture was in daytime, Oct-Dec 2022, and images were cropped to the lesion area. I looked at the paper's Fig. 4 sample panel (10 tomato images). Most show leaves on the plant with foliage behind them. One leaf-blight sample is a single leaf on a plain light background, one verticillium sample is against bright sky, and a few have small marks in the bottom-right corner that look like watermarks. Provenance is inconsistent. The paper names a Canon EOS Rebel T7 DSLR (native 6000x4000), yet lists original sizes of 400x400, 487x1080, 1080x518 and 3024x4032, which look like phone or web images. The average raw tomato file is only about 49 KB, so the images are heavily downsized or cropped. The raw-file preview did not render in the browser and I did not download any images, so this rests on the 10 samples in Fig. 4 plus the authors' text.

**Images.** The paper and the page agree that raw tomato is 5,435 and augmented is 27,178. The paper's Table 2 does give per-class raw counts: Healthy 500, Leaf blight 1,301, Leaf curl 518, Septoria leaf spot 2,343, Verticillium wilt 773. The files actually hosted differ from that. My count from the Mendeley public API metadata: raw Tomato has 5,805 files (healthy 470, leaf blight 1,301, leaf curl 518, septoria 2,743, "verticulium wilt" 773). Only 5,351 of them are unique by SHA-256. Septoria alone has 448 duplicates, saved under a random suffix such as "septoria leaf spot1910_-KO9m8s.jpg". The augmented set has 27,168 files: test 5,445 (500/1,309/532/2,340/764) and train 21,723 (2,000/5,200/2,050/9,373/3,100). The usable figure is about 5,351 unique raw tomato images in 5 classes.

**License.** CC BY 4.0 (Creative Commons Attribution 4.0 International, http://creativecommons.org/licenses/by/4.0). Both the API's data_licence field and the per-file page ("Licence CC BY 4.0") say this. The licence note adds that "further permission may be required for any content within the dataset that is identified as belonging to a third party". The description's line "freely available for use by the research community" describes the intended audience; it is not a licence term.

**Commercial use.** yes. CC BY 4.0 allows commercial use, including training a model for the commercial CropSCOUT site, as long as you credit the authors (Mensah Kwabena et al., 2023, doi 10.17632/bwh3zbpkpv.1), link the licence, mark any changes and do not imply endorsement. One residual risk is unconfirmed: a few sample images carry corner marks that look like watermarks and may be third-party web images, which the third-party clause would not cover.

**Usefulness for a live field camera.** medium: this is free, commercially usable (CC BY 4.0) African field imagery of tomato leaves on the plant, which narrows the gap between PlantVillage-style images and what a phone camera sees. But it is labels only (no boxes), has about 5.35k unique images in 5 coarse or ambiguous classes, carries duplicates and some label noise, and its official split leaks badly. It fits a frame or crop classifier as an extra training source, after deduplication and a careful split. It is not suitable for training a live detector.

**Errors in the first claim.** 1) "Per-class counts were not confirmed" is wrong. The paper's Table 2 lists them (500/1,301/518/2,343/773 = 5,435), but the hosted files do not match: 5,805 raw files, of which 5,351 are unique, with healthy at 470 rather than 500 and septoria at 2,743 rather than 2,343. Augmented is 27,168, not 27,178.
2) The leakage problem is worse than "train and test drawn from the same originals": 4,084 of the 5,445 augmented tomato test images (75%) are byte-identical copies of images in train_set, in the same class. All per-class test-in-train overlaps were 74-75%. Any accuracy reported on the official augmented split is inflated.
3) The advice to "use the raw set only" is not enough. The raw set also has to be deduplicated by hash before splitting (454 duplicates, mostly septoria). One image sits in both the leaf blight and septoria folders, a label conflict. Also, 14 files in the verticillium wilt folder are named "leaf blight912_.jpg" and similar. They are not byte copies of the leaf-blight files, but they may be mislabelled.
4) "Leaf blight merges early and late blight" has no support. The authors never define "leaf blight", so the right wording is "unspecified blight (could be early, late, or both)".
5) The Ghana/Kenya "conflict" mostly has an explanation. The Data in Brief specifications table lists two data source locations: UENR in Sunyani, Ghana, and the African Technology Policy Studies Network in Nairobi, Kenya, which is the funder (grant AI4AFS/GR/AFS-1233809296). The 2025 STA-Net paper (arXiv 2509.03754) probably took "Ghana and Kenya" from that table. Nothing shows images were collected in Kenya.
6) Minor: the folder is spelled "verticulium wilt", and the paper says the experts were virologists and pathologists. There is also a camera/resolution inconsistency (a DSLR is named, but phone-size originals are listed), which hints at more than one source device.
Process note: the PMC figure page wrote to the user's clipboard when I clicked it in the browser pane (the app already warned the user).

### First claim

- Why relevant: This is the largest single-source set of farm-collected tomato images here, validated by plant virologists. It is African field data, so its cultivars, light and backgrounds are far from PlantVillage. Verticillium wilt and leaf curl are new.
- Caveats: Labels only, no boxes. 'Leaf blight' merges early and late blight, so the taxonomy is coarse. Use the raw set only: the augmented set has train and test drawn from the same originals. Some images have artificial backgrounds. A 2025 paper describes the source as Ghana and Kenya, which conflicts with the dataset page.

## Tomato leaf diseases (Daffodil International University, Bangladesh, 2025)

- **Link:** https://data.mendeley.com/datasets/93h9p62kg4/1 is correct (DOI 10.17632/93h9p62kg4.1, version 1, published 2025-03-10, the only version). Direct zip: https://data.mendeley.com/public-api/zip/93h9p62kg4/download/1. An anonymous request returns a 302 redirect to a presigned S3 URL. The download is free, needs no login, and is 372,798,614 bytes (about 373 MB). I did not download the full zip. I read its central directory with HTTP range requests and listed the files through the public API.
- **Used to train the current models:** No

### Checked

**Task.** Classification only. The zip holds folder-per-class JPGs under 'Tomato leaf diseases/Tomato Leaf/<class>/' with no annotation, box or mask files. Each image shows one detached leaf, so it is single-leaf classification.

**Capture.** REFUTED as 'field'. In all 44 images I looked at (2 per class plus 24 random), a single detached leaf lies on a sheet of white paper. They were shot outdoors in daylight, but no plant, canopy or soil is in frame. That is close to PlantVillage-style lab framing, not in-situ field capture. Light is NOT varied. I read the EXIF of 70 files and every capture time falls on 2025-02-25 between 12:21 and 13:42, about 81 minutes around midday. Classes were shot in separate bursts, for example Healthy (103 images) in about 4 minutes and Spider Mites (307) in about 5 minutes. Device: mostly 'iPhone 11 back dual wide camera', but the 166 files named IMG_####.jpg (73 in Cercospora, 93 in Early Blight) have EXIF model iPhone 14. That contradicts the page's statement that all images came from an iPhone 11. Location: EXIF GPS rounds to about 23.88N 90.31E, which is consistent with one site near the Daffodil International University campus (Khagan/Charabag, Ashulia/Savar). It is one site, not multiple farms or 'a variety of regions' as the page's methods section says. Images are 4032x3024 but only about 110-350 KB each (median about 155 KB), so JPEG compression is heavy (the page says 'compressed by 80%'). Filenames carry a leftover '%02d' batch-tool pattern, for example IMG_3612_%02d.jpg.

**Images.** 2,627 files, all .jpg (no PNG), in 10 class folders. The public API file listing and the zip central directory agree. By SHA-256 there are 2,622 unique images: the 5 extra are byte-identical copies in Late Blight (IMG_5593-5597 'IMG_xxxx 2_%02d.jpg'). Per folder: Leaf Miner 519, Tomato Leaf Curl Virus 394, Bacterial Spot 376, Insect Damage 336, Spider Mites 307, Early Blight 204, Late Blight 166 (161 unique), Cercospora leaf mold 156, Healthy 103, Leaf Mold 66. The 2,659 in the claim is the page's per-class sum, which includes 'Class 16 (Uncategorized/Other): 32 images'. Those 32 images are not in the published files.

**License.** CC BY 4.0, Creative Commons Attribution 4.0 International (http://creativecommons.org/licenses/by/4.0), per the dataset's data_licence field in the Mendeley public API.

**Commercial use.** yes. CC BY 4.0 allows commercial use and modification if you credit the authors (Hossain, Haque, Al Rafi, Talukder, Daffodil International University, DOI 10.17632/93h9p62kg4.1), link the license, mark any changes, and do not imply endorsement. Practical note: the images still carry EXIF GPS and device metadata, so strip it before redistributing any images.

**Usefulness for a live field camera.** low. Every image is a detached leaf on white paper from one site in one 81-minute session, so it does not match a live camera pointed at plants. It could serve only as a second-stage classifier on segmented leaf crops, or as cut-and-paste pest examples (Leaf Miner, Spider Mites), and only with a split by capture group.

**Errors in the first claim.** 1) Image count is wrong. There are 2,627 real files (2,622 unique), not 2,659. The 2,659 sum includes a 32-image 'Uncategorized' class that does not exist in the download. The claim's caveat to drop that class is moot, and its class list should not include it. 2) Capture is misdescribed. These are detached leaves on white paper, not in-field plant images. 3) 'Natural varied light' is false. Every image was taken within about 81 minutes around midday on one day (2025-02-25). 4) The claim says iPhone 11 only, but 166 images were taken with an iPhone 14. 5) 'Farms' is plural, but the EXIF GPS points to one site near DIU. 6) The concern about JPG plus JPEG/PNG duplicates is unfounded: every file is .jpg, and there are only 5 exact duplicates (Late Blight). The real problem is near-duplicates and session confounding: each class was shot as a contiguous burst of IMG numbers in a few minutes, so a random train/val split will leak. Split by IMG-number block or capture time. 7) The folder is named 'Healthy', not 'Healthy Leaves', and the description's '10 diseases' is really 9 disorder classes plus Healthy. Three of the nine (Leaf Miner, Spider Mites, Insect Damage) are pests, not diseases. 8) The 'why relevant' text calls these 'phone photos in the field' that match what a live scanner sees on real plants. That is overstated, because the paper background is a strong shortcut a model will learn. Correct parts of the claim: name, institution, 2025 date, classification task, no boxes, CC BY 4.0, the 10 per-class counts that exist, Healthy being small (103), and the separate 'Leaf Mold' and 'Cercospora leaf mold' folders. Not verified: 'already_used_by_cropscout: No' (I did not inspect the user's project), and label accuracy (the page says labels came from 'experts or through observational methods', and Leaf Mold samples look like general chlorosis).

### First claim

- Why relevant: Phone photos in the field with strong pest coverage: Leaf Miner, Spider Mites and generic Insect Damage. These are exactly the non-disease look-alikes a live scanner meets on real plants. Cercospora (black) leaf mold is a new class.
- Caveats: No boxes. Healthy has only 103 images. An 'Uncategorized' class should be dropped. 'Leaf Mold' and 'Cercospora Leaf Mold' are separate classes and need care when mapping. The page lists both JPG and JPEG/PNG formats, so check for re-encoded duplicates.

# Not fact-checked yet

## TFDD: Tomato Fruit Disease Detection dataset

- Link: https://data.mendeley.com/datasets/ktfnhjspjn
- Task: object-detection (YOLO TXT boxes, labelled in Roboflow)
- Capture: mixed (a field in Bhashanchar, Faridpur, plus a local market in Khilkhet, Dhaka)
- Images: 288 originals: Anthracnose 27, Blossom_end_rot 31, Cracking 35, Early_Blight 20, Fruitworm 61, Healthy 27, Late_Blight 38, Mold 49. 682 after 3x training-only augmentation.
- Classes: Fruit: Anthracnose, Blossom end rot, Cracking, Early blight, Fruitworm, Healthy, Late blight, Mold (8)
- License: CC BY 4.0 (v3, June 2025)
- Used to train the current models: No
- Caveats: Tiny: 20-61 originals per class, which is enough to bootstrap or test but not to train well. Part of it is market fruit (picked, not on the plant). All images are resized to 640x640. Train only on the 288 originals and re-split by original.

## Tomato Leaf and Fruit Disease Image Dataset (Netrokona University)

- Link: https://data.mendeley.com/datasets/9jxvtgh325/1 (duplicate record: https://data.mendeley.com/datasets/swtt5wy2pr/1)
- Task: classification
- Capture: field (the page says 'captured in actual fields'; Bangladesh)
- Images: 3,500 originals (24,500 after augmentation). Per-class counts are not stated.
- Classes: Healthy Leaf, Early Blight Leaf, Late Blight Leaf, Leaf Curl Leaf, Bushy Stunt Leaf, Healthy Fruit, Target Spot Fruit (7)
- License: CC BY 4.0
- Used to train the current models: No. Looked at (14 sample images, two per class): every one is a detached leaf on white card, not a field photo, whatever the page says.
- Caveats: The same content is published under two DOIs (Feb 2026 and May 2026), so download one only. There are no boxes. Use the originals only, since the augmented copies leak. The capture location within Bangladesh is unspecified. The fruit disease labels (only Target Spot) are thin.

## Taiwan Tomato Leaves dataset (part of 'Dataset of Tomato Leaves', Huang & Chang)

- Link: https://data.mendeley.com/datasets/ngdgg79rzb/1
- Task: classification
- Capture: mixed (single leaf, multiple leaves, plain and complex backgrounds; Taiwan)
- Images: 622 originals (Bacterial spot 100, Black leaf mold 67, Gray leaf spot 84, Healthy 106, Late blight 98, Powdery mildew 157, as reported in secondary listings) and 4,976 augmented. The same record also holds a 14,531-image PlantVillage-derived part.
- Classes: Bacterial spot, Black leaf mold (Pseudocercospora fuligena), Gray leaf spot (Stemphylium), Healthy, Late blight, Powdery mildew (6)
- License: CC BY 4.0
- Used to train the current models: Yes: the originals of healthy, bacterial spot and late blight, in the tomato-leaf condition model and the crop/type model ([field-classifier.md](field-classifier.md)).
- Caveats: Small and old (2020). All images are resized to 227x227, which is too low-resolution for close-up lesion detail. Do not import the PlantVillage-derived half; it duplicates PlantVillage, which CropSCOUT already uses. Augmented copies (rotations, mirrors, brightness) must stay grouped with their originals. The per-class counts come from a secondary listing, not the Mendeley page.

## Tomato Leaf Image Dataset (TLID/PTLID), Paraná, Brazil greenhouses

- Link: https://data.mendeley.com/datasets/kt64b2kh89/2
- Task: classification (TLID whole leaf; PTLID 32x32 patches)
- Capture: mixed / unknown (leaves from commercial greenhouses in North Paraná; capture background not stated)
- Images: 15,260 TLID images at 256x256 (the paper says 15,256). PTLID has 64 patches of 32x32 per leaf (the paper says 227,218). Per-class counts are not stated.
- Classes: Healthy, Leaf Miner, Powdery Mildew, Bacterial Spot, Whitefly, Powdery Mildew + Leaf Miner, Bacterial Spot + Leaf Miner (7)
- License: CC BY 4.0
- Used to train the current models: No, although it is already listed as a candidate ('tlid') in leaf-detection-yolo26/the source config
- Caveats: 256x256 single-leaf crops, probably not scene-level, so it fits a second-stage classifier rather than a detector. Never split PTLID patches apart from their parent leaf (CropSCOUT's own config already warns about this). The two image counts disagree. Whether 'Whitefly' means Bemisia or Trialeurodes is not stated. One region.

## Tomato Leaf Damage Progression (2026)

- Link: https://data.mendeley.com/datasets/s96sc8sh6y
- Task: object-detection (YOLO boxes) with severity stage
- Capture: mixed (original field captures cropped to single leaves, plus early-blight images from a public dataset, plus 600 synthetic Poisson-blended images)
- Images: 8,596 final images. Instance totals conflict: the Mendeley page says 20,291 annotations and a secondary summary says 14,084 labelled instances. About 2,930 original field captures of Fusarium and leaf miner.
- Classes: Fusarium spp., Leaf Miner, Early Blight, each in 3 severity levels: Initial, Intermediate, Advanced (9 labels)
- License: CC BY 4.0
- Used to train the current models: No
- Caveats: Images are cropped to single leaves, so they are not true scene-level frames. 600 images are synthetic. The 970 early-blight images come from an unnamed 'public Tomato Leaf Disease Dataset' and may duplicate PlantVillage or other sets CropSCOUT already uses. A median filter was applied to early-blight images only, a processing shortcut the model could learn to recognise. Capture location is not stated.

## Tomato Fruit Disease Detection (Roboflow Universe)

- Link: https://universe.roboflow.com/tomato-disease-detection-fcgsf/tomato-fruit-disease-detection
- Task: object-detection
- Capture: lab/studio (sampled images are picked fruit on a plain grey or white background; filenames are phone timestamps from Feb-Mar 2024)
- Images: 1,902 (4 versions; whether the 1,902 includes augmentation was not confirmed)
- Classes: Fruit: Anthracnose, Bacterial_Spot, Blossom end rot, Healthy Tomato, Spotted wilt Virus (5)
- License: CC BY 4.0 (declared on Roboflow)
- Used to train the current models: No
- Caveats: Studio capture of picked fruit, so on its own it will not transfer to on-plant live frames, much like Fruits-360. Very low usage (27 views, 5 downloads). There is no author documentation or pathologist review. The class balance is unknown.

## PlantVillage, tomato subset

- Link: https://github.com/spMohanty/PlantVillage-Dataset
- Task: classification
- Capture: lab/studio (one detached leaf on a uniform background)
- Images: 18,160 color images, counted with the GitHub API: Bacterial_spot 2,127, Early_blight 1,000, Late_blight 1,909, Leaf_Mold 952, Septoria 1,771, Spider_mites 1,676, Target_Spot 1,404, TYLCV 5,357, Tomato_mosaic_virus 373, healthy 1,591
- Classes: Bacterial spot, Early blight, Late blight, Leaf mold, Septoria leaf spot, Two-spotted spider mite, Target spot, Tomato yellow leaf curl virus, Tomato mosaic virus, Healthy (10)
- License: CC BY-SA 3.0 as recorded in CropSCOUT's provenance. The GitHub repo itself has no LICENSE file. CropSCOUT's own cropscout_sources.yaml flags share-alike obligations for model training.
- Used to train the current models: Yes, in part: 'plantvillage' (765 provenance-cleared rows) and 'plantvillage_official' (476 identity / 1,452 condition rows, the official Septoria and healthy subset)
- Caveats: Uniform background and fixed lighting teach background shortcuts. Many images are of the same leaf (CropSCOUT already groups them via a leaf map). Lots of Kaggle and Roboflow 'tomato' sets are PlantVillage re-uploads, such as the FYP 3,127 set and Tushar's 9.26k set, so dedupe against it. The share-alike license is a commercial risk.

# Search notes

I read the provenance file and the related source config without changing anything.

WHAT CROPSCOUT USES FOR TOMATO TODAY
Sources (from vision/private/dataset-provenance.json and the data-preparation script):
- plantdoc: detection boxes
- plantvillage and plantvillage_official
- tomato_leaf: Mendeley bpfd9cns5g v2
- fruits360: the studio photos behind Tomato_fruit_healthy

There are no tomato fruit disease classes. TLID is listed as a candidate in the source config but is not in the build. Of the 15 datasets above, only PlantDoc, Tomato Leaf v2 and PlantVillage are already used.

KEY POINT FOR LIVE CAMERA
Public in-field tomato data with bounding boxes is small. Counting only unique photos:
- SLIF-Tomato: 890
- Sichuan greenhouse: 1,026
- Tomato-Village: about 1,796
- PlantDoc tomato: 746 (already used)
- Tomato Leaf v2: 731 (already used)
- Atma Jaya: up to 8,439, but mixed quality and with many fork duplicates

So the realistic build is a two-stage pipeline:
1. A light leaf/fruit detector trained on the union of the boxed sets.
2. The existing classifier run on the detector's crops, with the field classification sets added: CCMT 5,435, the Daffodil set 2,659, Netrokona 3,500 and Taiwan 622.

Rules for that build:
- Dedupe across sources with perceptual hashing.
- Split by source photo, plant or day. Tomato-Village's own val split is entirely augmented copies of train photos, and the CCMT, Netrokona, SLIF and TFDD augmented releases leak in the same way.
- Keep the user's 16 real photos as the acceptance test, not source-group validation, as in the memory note on misleading validation.

Fruit gap: TFDD (8 boxed fruit classes, 288 originals), Sichuan (Fruit-region boxes) and Netrokona (Healthy Fruit and Target Spot Fruit) are the on-plant or field options. The Roboflow fruit set is studio-only.

Pests:
- Leaf miner / Tuta-type damage: Tomato-Village, the Daffodil set, Atma Jaya, TLID and Damage Progression.
- Whitefly: only TLID.
- Spider mites: the Daffodil set, Atma Jaya and PlantVillage.

EXAMINED BUT NOT RANKED
- PlantSeg (in-the-wild segmentation, web-scraped). Its license has changed across releases: the paper says CC BY-NC-ND 4.0, Zenodo v6 (Jul 2025) says CC BY 4.0, and the latest Zenodo version (Nov 2025) says CC BY-NC 4.0. Treat it as non-commercial. The 1,201-image Voxel51 test split has 181 tomato images across 7 diseases; the full tomato count is unknown.
- TomatoEbola (Nigeria, Tuta absoluta): 326 images, 784 healthy/infected leaf boxes. The Zenodo record 13324917 is declared CC BY 4.0 but access is restricted (request only).
- FieldPlant (Cameroon field set, IEEE Access 2023). A Roboflow mirror (xray-syh9d/fieldplant-b2utv) is CC BY 4.0 with 5,156 images and 6 tomato classes, but the tomato image count is unknown.
- GTLD (India, field, 2024, resized to 256x256): no per-class counts.
- 'Tomato Leaf Disease Classification Dataset in Pakistan' (Mendeley 3mbnb82mxd), which is apparently the same as Kaggle syedhashirali260 (7,200 images, exactly 1,200 per class). This one is suspicious: its folder names copy PlantDoc class names (e.g. Tomato_mold_leaf), and the whole set is about 99 MB, so it may be a re-upload of PlantDoc/PlantVillage.
- Kaggle ashishmotwani/tomato (about 25k images, lab plus in-the-wild). Its license reads 'Data files © Original Authors', so it is not usable.
- Mendeley rnbsw72zb5 (1,028 images, healthy/diseased only).
- Mendeley xc94xbg239 (fruit healthy vs infected only).
- TOM2024 (tomato, onion and maize; tomato breakdown unknown).
- Pisa Pest Sticky Traps (whitefly on yellow traps, not plants).

LICENSE NOTE
CropSCOUT's provenance file lists PlantDoc as CC BY-SA 4.0 in one block and CC BY 4.0 in another. Both GitHub repos say CC BY 4.0, so fix the provenance entry.
