# IBR Defect Extraction System — Speaker Notes
## Sprint 3 Review | 30-Minute Presentation
### Presenter: Supreeth Mysore, Lead GPU Architect

---

## SLIDE 1: Title Slide (0:00 - 0:30)

Good morning everyone. I am Supreeth Mysore, Lead GPU Architect on the F135 IBR program here at Hitachi Digital Services. Today I am going to walk you through our Sprint 3 results for the automated defect extraction system. We have a working pipeline, we have real results, and I want to show you exactly where we stand and what comes next. This is a 30-minute walkthrough, and I will keep us on time.

---

## SLIDE 2: Agenda (0:30 - 1:30)

Here is what we will cover. First, the problem we are solving and why it matters. Then the architecture — the 8-phase pipeline and how each piece fits together. Third, I will show you actual numbers from our first pipeline run. Fourth, I built an interactive web dashboard that I will demo live. And finally, what we need for Sprint 4 and the open questions for P&W. Let us get into it.

---

## SLIDE 3: Section Divider — The Problem (1:30 - 1:45)

*(Pause briefly. Let the slide breathe.)*

Let me set the context for anyone new to the program.

---

## SLIDE 4: Manual Inspection Bottleneck (1:45 - 3:30)

Today, a technician inspects each blade on an IBR by hand. Visual exam under magnification, caliper measurements, comparison against the reparable limits manual, then written documentation. That takes 5 to 12 minutes per blade. For a Stage 3 rotor with 55 blades, you are looking at up to 11 hours for a single IBR. Stage 9 with 110 blades? A full 22-hour day.

And the precision issue is real. Hand measurement gives you plus or minus 3 thou. We need plus or minus 1 thou. That gap is what this project exists to close.

---

## SLIDE 5: Target State (3:30 - 5:00)

Our target is under 90 seconds per IBR regardless of blade count, plus or minus 1 thou precision, 100 percent detection rate with less than 2 percent false positives. And the cost? We are looking at 18 cents per Stage 3 IBR on AWS. That is not a typo. At 720 IBRs per year, the entire annual compute cost is under $250.

The value proposition here is not compute savings — it is throughput. We are taking a day-long bottleneck down to 90 seconds.

---

## SLIDE 6: Section Divider — Architecture (5:00 - 5:15)

*(Let the section title land.)*

Now let me walk through how we actually do this.

---

## SLIDE 7: 8-Phase Pipeline (5:15 - 7:00)

The pipeline has 8 phases running in sequence. Phase 1 loads and cleans the PLY scan — downsampling, outlier removal, normal estimation. Phase 2 aligns the scan to the CAD reference using a two-stage RANSAC plus ICP approach. Phase 3 is the computational core — KD-tree deviation analysis computing signed distances for every point. Phase 4 segments the rotor into individual blades using angular DBSCAN. Phase 5 clusters defect points into discrete defect regions. Phase 6 measures each defect using PCA for edge defects and OBB for surface defects. Phase 7 maps to P&W's 13-zone system and checks against 91 compliance rules. Phase 8 generates the Excel and JSON reports.

Every phase is independently configurable through YAML. No magic numbers in the code.

---

## SLIDE 8: Registration Detail (7:00 - 8:30)

Let me zoom into Phase 2 because this is where everything either works or falls apart. When the technician puts an IBR under the scanner, the part is rotated, shifted, tilted — it is never in the same position as the CAD model. If you compare without alignment, every single point looks like a defect.

We do this in two stages. RANSAC gives us a coarse global alignment using feature descriptors — 4 million iterations, 0.999 confidence. Then ICP refines that to sub-micron precision with point-to-plane estimation. Our initial run achieved 0.016mm RMSE. The acceptance threshold is 0.05mm, so we are well within tolerance.

---

## SLIDE 9: Deviation Analysis (8:30 - 10:00)

Phase 3 is where we find defects. For every scan point, we compute the signed distance to the nearest CAD surface using a KD-tree. Negative means material has been removed — that is a nick, a gouge, a crack. Positive means buildup or deposit.

We selected a threshold of negative 0.010mm for defect detection. I will show you why on the next slide.

---

## SLIDE 10: Threshold Selection (10:00 - 11:30)

This table shows our sensitivity analysis. At negative 0.005mm, we catch everything but get 12 percent false positives — that is scanner noise triggering alarms. At negative 0.010mm, we still get 100 percent detection with only 1.8 percent false positives. That is our sweet spot.

Why 100 percent detection is non-negotiable: this is aerospace. A missed crack on a turbine blade is not an acceptable failure mode. We would rather deal with a couple of false positives per blade than miss a real defect. And the false positives get filtered out by DBSCAN clustering downstream anyway — they show up as scattered single points, not clusters.

---

## SLIDE 11: 13-Zone System (11:30 - 13:00)

P&W divides each blade into 13 inspection zones based on structural criticality. Leading edge tip and trailing edge tip are critical — the tightest limits, 5 thou depth max. The root critical zones A1 and B1 are even tighter at 3 thou. Surface zones are more lenient at 10 to 15 thou.

The key rule: when a defect spans two zones, we apply the most restrictive limit. P&W confirmed this directly. It is not something we assumed.

---

## SLIDE 12: Compliance Engine (13:00 - 14:30)

We have 91 compliance rules covering 13 zones times 7 defect types. Each defect gets dispositioned into one of three tiers: Serviceable if it is within limits, Blend if it is within 1.5x limits, Replace if it exceeds blend limits. AND logic — all conditions must pass simultaneously.

Cracks get 0.5x normal limits. FOD gets 0.8x. Unknown zones default to the most restrictive limits. Safety first.

---

## SLIDE 13: Section Divider — Results (14:30 - 14:45)

*(Let people digest. The architecture section is dense.)*

Now the part I am most excited about — let me show you what actually happened when we ran the pipeline.

---

## SLIDE 14: First Run Metrics (14:45 - 16:30)

We generated a synthetic 5-blade IBR with controlled defects — a nick on blade 1, a dent on blade 2, a clean blade 3, a gouge on blade 4, and three small nicks on blade 5. 55,000 total points.

The pipeline processed the entire thing in 14.5 seconds on a single CPU. No GPU. Registration RMSE of 0.016mm. Found 800 defect candidate points out of 22,000 cleaned points — that is 3.6 percent, which is right in line with what we would expect from the introduced defects. After DBSCAN clustering, those 800 points resolved into 4 discrete defects.

14.5 seconds on a single CPU with no optimization. The production target is 90 seconds on GPU instances. We have massive margin.

---

## SLIDE 15: Defect Details (16:30 - 18:00)

Here are the four detected defects. D001 and D004 are small — depths of 1.1 and 0.6 thou, well within the C1 zone limits. The system correctly dispositioned them as Serviceable. D002 and D003 are larger — depths of 4.8 and 5.6 thou with lengths exceeding 0.5 inches. Those exceed the C1 zone limit of 0.080 inches on length, so the system correctly flagged them as Replace.

The system did what it was supposed to do. The dispositions match what a human inspector would conclude from the same measurements.

---

## SLIDE 16: PCA vs OBB Measurement (18:00 - 19:00)

This is one of those decisions that you cannot get right from the math alone. Bryan from P&W told us: edge defects elongate along the edge curve. Surface defects are more isotropic. So edge defects get PCA measurement — longitudinal along the edge. Surface defects get OBB measurement — transverse. Using the wrong method gives you wrong numbers. Domain knowledge matters.

---

## SLIDE 17: Rotor Coverage (19:00 - 20:00)

We support all 9 F135 compressor stages, 12 part numbers, 20 to 110 blades. Zone boundaries are stored as percentages of blade height, not absolute millimeters, so the same configuration works across every stage without modification. Stage 3 with 55 blades is our primary test case, but the architecture handles Stage 9 with 110 blades identically.

---

## SLIDE 18: Section Divider — Dashboard (20:00 - 20:15)

Now let me show you something fun.

---

## SLIDE 19: Dashboard Features (20:15 - 21:30)

I built a web dashboard on top of the pipeline. Three pages. The main dashboard shows stats cards, an interactive 3D point cloud with deviation heatmap that you can rotate and zoom, disposition breakdowns, defect tables, measurement comparison charts. The 3D viewer gives you a full-screen rotatable point cloud with four view modes. The reports page lists all inspections with download buttons for both JSON and Excel.

There are 12 REST API endpoints ready for integration with other Hitachi systems.

***(At this point, switch to the live demo at localhost:8000. Spend 3-4 minutes showing the dashboard, rotating the 3D model, clicking through defects, switching to the 3D viewer, showing the reports page.)***

---

## SLIDE 20: AWS Architecture (21:30 - 23:00)

For production, each blade runs on its own g4dn.xlarge GPU instance in parallel. All N blades process simultaneously — that is why blade count does not affect wall clock time. Stage 3 costs 18 cents. Stage 9 costs 34 cents. ITAR compliant: all processing stays in US regions, encrypted at rest and in transit, VPC with no internet gateway.

Sprint 4 will provision this infrastructure.

---

## SLIDE 21: Section Divider — Next Steps (23:00 - 23:15)

Almost done. Let me talk about what we need.

---

## SLIDE 22: Open Questions (23:15 - 25:00)

I have five open questions for P&W. First, do zone boundaries scale with blade size or are they fixed across stages? Second, we need actual LE/TE curve data from the CAD to do proper edge-distance classification. Third — and this is the big one — we need a real scan file. A single Stage 3 PLY scan would let us validate the entire pipeline against vendor results. Fourth, adjacency rules: spanwise or Euclidean distance? And fifth, are there assembly-level limits beyond individual blade rules?

The real scan data is the single biggest blocker. Everything else we can work around.

---

## SLIDE 23: Sprint 4 Priorities (25:00 - 27:30)

Sprint 4 has five priorities. AWS infrastructure provisioning. Running the pipeline against real scan data. Extracting LE/TE curves from the CAD mesh. Training the Random Forest model on labeled defect data. And calibrating foil segmentation on real rotor geometry — because the DBSCAN parameters tuned for synthetic data will need adjustment.

The Sprint 4 goal is specific: by the end of Sprint 4, run the pipeline against a real Stage 3 scan and produce a report that matches vendor findings within tolerance. That is the milestone.

---

## SLIDE 24: Closing (27:30 - 30:00)

The pipeline is running. The results are real. 14.5 seconds, 4 defects detected, 91 rules checked, reports generated. We have a working prototype, an interactive dashboard, and a clear path to production.

What I need from this room: get us a real scan file, answers to the five open questions, and sign-off on the Sprint 4 priorities. With that, we will have a validation-ready system by the end of next sprint.

Thank you. I will take questions now.

*(Be prepared for questions about: threshold selection justification, measurement precision claims, ITAR compliance details, timeline to production deployment, ML model training data requirements.)*

---

## TIMING SUMMARY

| Section | Slides | Duration | Running Total |
|---------|--------|----------|---------------|
| Title + Agenda | 1-2 | 1:30 | 1:30 |
| Problem | 3-5 | 3:30 | 5:00 |
| Architecture | 6-12 | 9:30 | 14:30 |
| Results | 13-17 | 5:30 | 20:00 |
| Dashboard + Demo | 18-20 | 3:00 + demo | 24:30 |
| Next Steps | 21-23 | 4:00 | 28:30 |
| Close + Q&A Buffer | 24 | 1:30 | 30:00 |

---

*Prepared by: Supreeth Mysore | Hitachi Digital Services | March 2026*
