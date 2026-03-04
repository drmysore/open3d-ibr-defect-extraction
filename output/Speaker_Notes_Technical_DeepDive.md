# IBR Technical Deep-Dive — Speaker Notes
## Template Creation & Hybrid Network Architecture
### Presenter: Supreeth Mysore | 30-Minute Presentation

---

## S1: Title (0:00 – 0:30)

Hey everyone. Last time I showed you the pipeline overview and initial results. Today I want to go deeper — into the actual data structures and algorithms that make this work. How the template gets built, why we chose a hybrid grid-plus-mesh approach, and I will walk through actual code from the FastAPI dashboard. This is the technical "how" behind the "what" from last session.

---

## S2: Agenda (0:30 – 1:30)

Six sections. First, the template architecture — why we need two data structures instead of one. Then the voxel grid and KD-tree independently, so you see what each brings to the table. Zone template mapping — how every point maps to one of P&W's 13 zones. A results walkthrough where I trace a single defect through all 8 phases. And finally, a code walkthrough of the FastAPI dashboard. Let me start with architecture.

---

## S3: Section 01 — Template Architecture (1:30 – 1:45)

*(Let the section title sit for a moment.)*

---

## S4: Why Hybrid Grid + Mesh? (1:45 – 3:30)

This is the fundamental design decision. We have two different types of queries in this pipeline. First: "given a 3D coordinate, which voxel cell does it belong to?" That is a grid problem. O(1) — just divide by cell size and floor. Second: "given a scan point, what is the nearest CAD surface point?" That is a spatial search problem. The grid cannot answer it because CAD geometry is not uniformly distributed.

So we use both. The voxel grid handles downsampling and cell-based zone lookup. The KD-tree handles nearest-neighbor queries for deviation analysis, outlier detection, and adjacency checks. Each handles what it is good at. This is not over-engineering — try removing either one and the pipeline breaks.

---

## S5: Template Creation Pipeline (3:30 – 5:00)

Five steps to build the template. Load the PLY, that gives us 55,000 raw points. Voxel discretization reduces to 22,000 unique cells. Statistical filter uses a KD-tree to find isolated noise points and removes them — 481 points gone. Normal estimation runs PCA on each point's 30 nearest neighbors to compute the surface normal direction. The output is 22,064 points, each with an XYZ position, a grid cell index, and a surface normal vector. That IS the template. Everything downstream queries this structure.

---

## S6: Voxel Downsampling Code (5:00 – 6:30)

Three lines of NumPy. Floor each coordinate by the voxel size to get a grid cell address. Find unique cell addresses. Keep one point per cell. That is it. 55,000 down to 22,545.

The key engineering decision: 0.5mm voxel size. Our measurement requirement is plus or minus 0.001 inches, which is 0.025mm. So 0.5mm voxels give us 50 times finer resolution than what we actually need to measure. That margin is deliberate. If someone tells me the scanner data is denser than expected, I have room to go finer without breaking anything.

---

## S7: Statistical Outlier Removal (6:30 – 8:00)

This is where the KD-tree first appears. For every point, query its 20 nearest neighbors and compute the average distance. Then compute the global mean and standard deviation of those averages. Any point whose mean neighbor distance exceeds 2.5 sigma gets removed. 481 points out of 22,545 — that is 2.1 percent.

These are scanner artifacts — points floating in space where there is no actual surface. Without this filter, they show up as isolated deviation spikes that look like defects but are not real. The KD-tree makes this efficient because computing 20-nearest-neighbors for 22,000 points is trivial with a spatial index.

---

## S8: Section 02 — KD-Tree Mesh (8:00 – 8:15)

---

## S9: What is a KD-Tree? (8:15 – 9:45)

For anyone not familiar: a KD-tree is a binary tree that recursively partitions 3D space. At each level, it splits on one axis — X, then Y, then Z, then back to X. The result is a tree where finding the nearest neighbor costs log-n instead of n.

Concrete numbers: brute force on 22,000 points is 484 million distance comparisons. The KD-tree does it in about 330,000. That is a 1,500x speedup. We use scipy's cKDTree which is implemented in C and uses all available CPU cores. The entire deviation analysis — 22,000 signed distances — takes under 0.1 seconds.

---

## S10: KD-Tree Across the Pipeline (9:45 – 11:00)

The KD-tree shows up in four places. Phase 1 outlier removal — k-nearest-neighbor distances to find noise. Phase 2 ICP registration — iteratively matching scan points to CAD points. Phase 3 deviation analysis — this is the big one, computing signed distances for every point. And the defect library uses it for adjacency detection — finding defects that are close to each other.

If you take the KD-tree out, Phase 3 alone would exceed our 90-second budget. It is non-optional infrastructure.

---

## S11: Signed Distance Math (11:00 – 13:00)

Here is the actual math. For each scan point p-sub-i, find the nearest CAD point c-sub-j using the KD-tree. Get the surface normal n-sub-j at that CAD point. Compute the dot product of the difference vector with the normal. If the scan point is behind the CAD surface — material has been removed — the dot product is negative. That is a defect.

The implementation is fully vectorized. One call to tree.query gives us all 22,000 nearest-neighbor indices. One NumPy subtraction gives all difference vectors. One NumPy sum along axis 1 gives all signed distances. No Python loops. This is why it runs in 0.1 seconds instead of 30 minutes.

---

## S12: Deviation Results (13:00 – 14:00)

The numbers from our run. 22,064 points analyzed. Deviation range is minus 0.14 to plus 0.13 millimeters. Mean is negative 0.0008 — essentially zero, which tells us the alignment is excellent. 800 points fell below the negative 0.010mm threshold — 3.6 percent of the total. Those 800 points collapsed into 4 distinct defect clusters after DBSCAN.

---

## S13: Section 03 — Zone Template (14:00 – 14:15)

---

## S14: Two-Layer Zone Design (14:15 – 15:30)

This was an important architecture decision. We store zone boundaries as percentages, not absolute millimeters. A1 is 0 to 3.83 percent of blade span. A2 is 3.83 to 62.88 percent. At runtime, we multiply by the actual measured blade span from ICP alignment.

Why measured and not nominal? Because real blades are not nominal. A blade with 2mm of tip erosion has a different effective span than a new blade. Using the ICP-measured span means zone boundaries track the actual geometry. And the same percentage config works across all 9 F135 stages — no per-stage configuration needed.

---

## S15: Zone Classification Logic (15:30 – 17:00)

The decision tree. Is it an edge defect near the leading edge? Match against A1, A2, or A3 by span percentage. Near trailing edge? Match B1 or B2. Surface defect? Default to C1 convex or C2 concave.

But here is the important part — we always check tip zones regardless of the primary classification. A defect at 95 percent span on the leading edge gets both A3 AND LE_TIP limits applied. And when a defect is in multiple zones, we take the most restrictive limit. P&W confirmed this directly.

---

## S16: Compliance AND Logic (17:00 – 18:00)

Three tiers. Serviceable if depth AND length are within limits. Blend if within 1.5x. Replace if beyond. AND logic means both dimensions must pass simultaneously. You cannot have a defect that is safe on depth but too long and call it serviceable.

Cracks get half the normal limits. FOD gets 0.8x. Unknown zones default to most restrictive. These are safety decisions, not engineering preferences.

---

## S17: Section 04 — Defect Library (18:00 – 18:15)

---

## S18: DefectLibrary Architecture (18:15 – 19:30)

The defect library stores every detected defect and provides four dimensions of query. Primary store is a simple dictionary. Secondary indices by foil number and by zone give instant lookup without scanning. A KD-tree on defect centroids enables spatial adjacency queries.

The four dimensions: D1 asks where is the defect — grid O(1) or metric O(log n). D2 asks which zone — percentage comparison. D3 asks about cross-zone effects — aggregate queries across zones. D4 asks about the whole rotor — cross-foil analysis. Each dimension has its own optimized query path.

---

## S19: Adjacency Code (19:30 – 20:30)

The adjacency function uses query_ball_point — give it a center and a radius, and it returns all points within that radius in O(log n). This matters because two small defects 3mm apart might individually pass limits but together represent a structural concern. The P&W reparable limits manual has proximity rules that we need to check.

---

## S20: Section 05 — Results Walk (20:30 – 20:45)

---

## S21: Defect F001_D002 Full Trace (20:45 – 22:30)

Let me trace one defect through the entire pipeline. F001_D002. It starts as part of 55,000 raw points and survives the voxel filter and outlier removal. After alignment, 345 of its constituent points show signed distances between -0.048 and -0.122mm — all well below our -0.010mm threshold. DBSCAN groups those 345 points into one cluster. OBB measurement gives us 0.596 inches length and 0.0048 inches depth. Zone classification puts it in C1 and E2. C1 allows max length 0.080 inches. This defect is at 0.596 inches — seven times over the limit. Disposition: REPLACE.

Every phase contributed to that outcome. Remove the outlier filter and you might miss it. Remove ICP and the distances are wrong. Remove zone classification and you do not know the limit to check against.

---

## S22: All 4 Results (22:30 – 23:30)

All four defects in the table. D001 and D004 are small, well within limits — serviceable. D002 and D003 are large, exceeding the C1 max length by 7x — replace. The system matched expected outcomes on all four controlled defects. This is synthetic data, so we know exactly what was injected and can verify the pipeline got it right.

---

## S23: PCA vs OBB (23:30 – 24:30)

Quick note on measurement method. Edge defects use PCA because they elongate along the edge curve. Surface defects use OBB because they are more isotropic. Using PCA on a surface defect or OBB on an edge defect gives you the wrong numbers. This came from Bryan at P&W — it is domain knowledge you cannot derive from algorithms.

---

## S24: Section 06 — FastAPI Dashboard (24:30 – 24:45)

Now let me show you the code behind the dashboard.

---

## S25: FastAPI Stack (24:45 – 26:00)

The stack is FastAPI for async Python, Jinja2 for templates, and Plotly.js for 3D rendering in the browser. The key insight is that the API endpoints use the exact same KD-tree math from Phase 3. The deviation endpoint reads both PLY files, builds a KD-tree from the CAD, queries all scan points, computes signed distances, and returns them as JSON. 30,000 signed distances per API call, computed on-the-fly.

---

## S26: Dashboard Elements (26:00 – 27:00)

Six visual elements on the main page. Stats cards across the top. The 3D heatmap is the centerpiece — 30,000 points rendered as a Plotly scatter3d with deviation colorscale. Disposition donut chart. Zone distribution bar chart. Defect table with colored badges. And a depth comparison bar chart.

Everything reads from the pipeline output JSON. Re-run the pipeline, refresh the browser, it updates.

---

## S27: 3D Viewer Code (27:00 – 28:00)

The 3D viewer has four modes. The Plotly.js code is straightforward — pass X, Y, Z arrays and a color array to scatter3d. Plotly uses WebGL under the hood so the browser GPU does the rendering. 50,000 points render smoothly. No server-side rendering needed — the server just sends the point data as JSON.

---

## S28: API Endpoints (28:00 – 28:30)

12 REST endpoints. The important ones for integration: /api/pipeline/run triggers execution, /api/pipeline/status polls progress, /api/report/latest gets the result. Any Hitachi system can integrate with these.

---

## S29: Discussion Questions (28:30 – 29:30)

Six questions I need input on. Should we go finer than 0.5mm voxels for production? Would an R-tree be better for zone polygon queries? How do we auto-extract LE/TE curves from the CAD mesh? Should 3-plus-zone defects get flagged for manual review? What other systems need API access? And the big one — when do we get real scan data?

Items 3 and 6 are blockers. Without LE/TE curves, edge classification stays approximate. Without real scan data, we cannot validate against vendor results.

---

## S30: Close (29:30 – 30:00)

The template is built. Grid discretization plus KD-tree mesh gives us hybrid precision at production speed. The code is on GitHub, the dashboard is live, the results match expectations. What I need: answers on those six questions, especially LE/TE extraction and real scan data, before Sprint 4 kicks off.

Thank you. Questions?

---

## TIMING SUMMARY

| Section | Slides | Duration | Running |
|---------|--------|----------|---------|
| Title + Agenda | 1-2 | 1:30 | 1:30 |
| Template Architecture | 3-7 | 6:30 | 8:00 |
| KD-Tree Mesh | 8-12 | 6:00 | 14:00 |
| Zone Template | 13-16 | 4:00 | 18:00 |
| Defect Library | 17-19 | 2:30 | 20:30 |
| Results Walkthrough | 20-23 | 4:00 | 24:30 |
| FastAPI Dashboard | 24-28 | 4:00 | 28:30 |
| Discussion + Close | 29-30 | 1:30 | 30:00 |

---

*Prepared by: Supreeth Mysore | Hitachi Digital Services | March 2026*
