# Architecture Overview — civil3d-mcp

> **civil3d-mcp** is a [Model Context Protocol](https://modelcontextprotocol.io) server
> written in Python 3.11 that lets Claude Desktop drive Autodesk Civil 3D directly
> via Windows COM automation — no companion plugin, no TCP socket, no extra process.

---

## 1. System overview

```
┌────────────────────────────────────────────────────────────────────┐
│  Windows Machine (same desktop session)                            │
│                                                                    │
│  ┌──────────────────┐  stdio (MCP)  ┌───────────────────────────┐  │
│  │  Claude Desktop  │◄─────────────►│  civil3d-mcp              │  │
│  │  (MCP client)    │               │  FastMCP · Python 3.11    │  │
│  └──────────────────┘               │                           │  │
│                                     │  ┌─────────────────────┐  │  │
│                                     │  │  Civil3DClient      │  │  │
│                                     │  │  win32com  pythonnet│  │  │
│                                     │  └────────┬────────────┘  │  │
│                                     └───────────┼───────────────┘  │
│                                                 │ COM / IDispatch  │
│                                     ┌───────────▼───────────────┐  │
│                                     │  Autodesk Civil 3D        │  │
│                                     │  acad.exe (running)       │  │
│                                     │                           │  │
│                                     │  AeccDbMgd.dll            │  │
│                                     │  AeccLandMgd.dll          │  │
│                                     │  acdbmgd.dll              │  │
│                                     └───────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

**Key constraint:** All three processes run on the same Windows machine in the
same desktop session. COM `GetActiveObject` only works within the same session.

---

## 2. Layer breakdown

### Layer 1 — Claude Desktop (MCP client)

Claude Desktop spawns the `civil3d-mcp` process as a child and communicates
with it over **stdin/stdout** using the [MCP JSON-RPC wire format](https://spec.modelcontextprotocol.io).

Claude sees 19 tools (listed in §5). When the user sends a prompt, Claude
decides which tool(s) to call, sends a `tools/call` request, receives the
JSON result, and weaves it into its reply.

### Layer 2 — FastMCP server (this project)

```
server.py
│
├── on_startup()        ← Civil3DClient.connect() in ThreadPoolExecutor
│
├── on_shutdown()       ← Civil3DClient.disconnect()
│
├── tools_drawing.py    ─┐
├── tools_cogo.py        │  register(mcp, client)
├── tools_lines.py       │  each file adds @mcp.tool decorated
├── tools_surfaces.py    │  async functions to the FastMCP app
├── tools_alignments.py  │
└── tools_corridors.py  ─┘
```

**Threading model:**  
FastMCP runs an asyncio event loop. COM calls are synchronous (blocking).
A single-thread `ThreadPoolExecutor` named `civil3d-com` is used to run all
`Civil3DClient` methods via `loop.run_in_executor(...)` so the event loop
is never blocked. The executor has `max_workers=1` — this serialises all
COM calls, which is required because Civil 3D's COM interface is not
thread-safe (it lives in an STA apartment).

### Layer 3 — Civil3DClient (COM bridge)

```python
# Win32 COM layer — AutoCAD base objects
import win32com.client as w32
app = w32.GetActiveObject("AeccXUiLand.AeccApplication.14.0")
doc = app.ActiveDocument          # AeccDocument
doc.CogoPoints                    # ICogoPointCollection
doc.AlignmentsSiteless            # IAlignmentCollection
doc.Surfaces                      # ISurfaceCollection

# pythonnet managed layer — Civil 3D .NET types
import clr
clr.AddReference(r"...\AeccDbMgd.dll")
clr.AddReference(r"...\AeccLandMgd.dll")
from Autodesk.Civil.DatabaseServices import TinSurface, Alignment
```

The two layers complement each other:
- **win32com IDispatch** exposes all COM-registered interfaces — enough for
  drawing queries, COGO point CRUD, basic line/polyline creation.
- **pythonnet clr** exposes the richer managed .NET API — required for surface
  statistics (`Statistics.Area2D`, `FindElevationAtXY`), alignment entity
  enumeration, and `StationOffset` with by-reference out-parameters.

### Layer 4 — Autodesk Civil 3D

Civil 3D registers itself as a COM server under two ProgIDs when it launches:

| ProgID | Covers |
|---|---|
| `AeccXUiLand.AeccApplication.14.4` | Civil 3D 2026 |
| `AeccXUiLand.AeccApplication.13.7` | Civil 3D 2025 |
| `AeccXUiLand.AeccApplication.14.0` | Civil 3D 2024 |
| `AeccXUiLand.AeccApplication.13.0` | Civil 3D 2023 |
| `AutoCAD.Application` | Base AutoCAD (fallback, no Civil 3D types) |

The server tries them in order and uses the first that responds.

---

## 3. Request lifecycle

```
User: "What is the elevation of surface EG at easting 45200, northing 87300?"

   Claude Desktop
        │
        │  tools/call  sample_surface_elevation
        │  {"surface_name":"EG","easting":45200,"northing":87300}
        ▼
   FastMCP (asyncio event loop)
        │
        │  loop.run_in_executor(_executor, client.sample_surface_elevation, ...)
        ▼
   ThreadPoolExecutor  [civil3d-com thread]
        │
        │  self._find_surface("EG")
        │      → iterates doc.Surfaces COM collection
        │  surf.FindElevationAtXY(45200, 87300)
        │      → COM call into acad.exe process
        ▼
   Civil 3D  (in-process COM server)
        │
        │  returns: 12.47  (float)
        ▼
   ThreadPoolExecutor  [result back to event loop]
        │
        │  {"surface_name":"EG","easting":45200,"northing":87300,"elevation":12.47}
        ▼
   FastMCP  →  tools/result  →  Claude Desktop
        │
        ▼
   Claude: "The elevation of surface EG at easting 45200, northing 87300 is 12.47 m."
```

---

## 4. COM connection strategy

```python
# Tried in order at connect():
PROG_IDS = [
    "AeccXUiLand.AeccApplication.14.0",   # Civil 3D 2024 / 2025
    "AeccXUiLand.AeccApplication.13.0",   # Civil 3D 2023
    "AutoCAD.Application",                # plain AutoCAD fallback
]
for prog_id in PROG_IDS:
    try:
        self._acad = win32com.client.GetActiveObject(prog_id)
        break
    except Exception:
        continue
```

`GetActiveObject` connects to the **already-running** instance registered in
the Windows Running Object Table (ROT). If Civil 3D is not running, or no
drawing is open, the connection fails with a descriptive `Civil3DError`.

### Managed assembly loading

After the COM connection is established, pythonnet loads Autodesk's .NET DLLs:

```
CIVIL3D_BIN_PATH (env var)
    │
    ├── AeccDbMgd.dll       ← Civil 3D database managed layer
    ├── AeccLandMgd.dll     ← Civil 3D land/survey managed layer
    └── acdbmgd.dll         ← AutoCAD base managed layer

Auto-detected paths (tried in order):
    C:\Program Files\Autodesk\AutoCAD 2025\
    C:\Program Files\Autodesk\AutoCAD 2024\
    C:\Program Files\Autodesk\AutoCAD 2023\
```

If the DLLs cannot be found, the server falls back to pure IDispatch COM —
drawing info and line creation still work, but surface statistics and
alignment geometry may be limited.

---

## 5. Tool inventory

| # | Tool | Module | COM collection used |
|---|---|---|---|
| 1 | `get_drawing_info` | tools_drawing | `doc.Name`, `doc.GetVariable()` |
| 2 | `list_civil_object_types` | tools_drawing | `doc.ModelSpace`, named collections |
| 3 | `get_selected_objects_info` | tools_drawing | `doc.SelectionSets` |
| 4 | `create_cogo_point` | tools_cogo | `doc.CogoPoints.Add()` |
| 5 | `list_cogo_points` | tools_cogo | `doc.CogoPoints` iterator |
| 6 | `delete_cogo_point` | tools_cogo | `doc.CogoPoints.Delete()` |
| 7 | `create_line` | tools_lines | `doc.ModelSpace.AddLine()` |
| 8 | `create_polyline` | tools_lines | `doc.ModelSpace.Add3DPoly()` |
| 9 | `list_lines` | tools_lines | `doc.ModelSpace` iterator |
| 10 | `list_surfaces` | tools_surfaces | `doc.Surfaces` iterator |
| 11 | `get_surface_info` | tools_surfaces | `surf.Statistics` |
| 12 | `sample_surface_elevation` | tools_surfaces | `surf.FindElevationAtXY()` |
| 13 | `list_surface_definition` | tools_surfaces | `surf.DataDefinition` collections |
| 14 | `list_alignments` | tools_alignments | `doc.AlignmentsSiteless` |
| 15 | `get_alignment_info` | tools_alignments | `al.Entities` iterator |
| 16 | `get_station_offset` | tools_alignments | `al.StationOffset()` (out-params) |
| 17 | `list_profiles` | tools_alignments | `al.Profiles` iterator |
| 18 | `get_profile_info` | tools_alignments | `al.Profiles` item |
| 19 | `get_corridor_info` | tools_corridors | `doc.Corridors` iterator |

---

## 6. Project file structure

```
civil3d-mcp-python/
│
├── src/
│   └── civil3d_mcp/              Python package (src layout)
│       ├── __init__.py           Public API: Civil3DClient, Civil3DError
│       ├── server.py             FastMCP app · lifecycle · tool registration
│       ├── client.py             Civil3DClient · all COM/pythonnet calls
│       ├── tools_drawing.py      Tools 1–3   (drawing info)
│       ├── tools_cogo.py         Tools 4–6   (COGO points)
│       ├── tools_lines.py        Tools 7–9   (lines & polylines)
│       ├── tools_surfaces.py     Tools 10–13 (surfaces)
│       ├── tools_alignments.py  Tools 14–18 (alignments & profiles)
│       └── tools_corridors.py   Tool  19    (corridors)
│
├── tests/
│   ├── __init__.py
│   └── test_tools.py             pytest suite · fully mocked Civil3DClient
│
├── setup.py                      Legacy setuptools entry (pip editable install)
├── pyproject.toml                PEP 517/518 build config · tool config
├── requirements.txt              Runtime dependencies
├── requirements-dev.txt          Dev/test dependencies
├── conftest.py                   pytest sys.path injection
├── setup_check.py                Pre-flight environment checker
├── .env.example                  Environment variable template
├── claude_desktop_config_snippet.json   Claude Desktop config snippet
├── ARCHITECTURE.md               ← this file
└── README.md                     Installation & usage guide
```

---

## 7. Data flow for COM out-parameters

Civil 3D's `StationOffset` method uses COM by-reference out-parameters —
a pattern not natively supported by Python. The server handles it with
mutable `VARIANT` objects:

```python
# WRONG — plain floats are immutable, COM cannot write back into them
station = 0.0
offset  = 0.0
al.StationOffset(easting, northing, station, offset)   # station/offset unchanged

# CORRECT — VT_R8|VT_BYREF VARIANTs are mutable COM references
station_var = win32com.client.VARIANT(pythoncom.VT_R8 | pythoncom.VT_BYREF, 0.0)
offset_var  = win32com.client.VARIANT(pythoncom.VT_R8 | pythoncom.VT_BYREF, 0.0)
al.StationOffset(easting, northing, station_var, offset_var)
result_station = float(station_var.value)   # Civil 3D wrote the value here
result_offset  = float(offset_var.value)
```

The `_out_double()` helper in `Civil3DClient` encapsulates this pattern.

---

## 8. Error handling strategy

Every public `Civil3DClient` method raises `Civil3DError` (a `RuntimeError`
subclass) on failure. Tool functions catch it and return `{"error": "<msg>"}`.
Claude receives this dict and surfaces the message to the user in natural
language. This means:

- No tool ever raises an unhandled exception into FastMCP.
- The MCP server stays alive even if a single tool call fails.
- Claude can explain the error to the user and suggest remedies.

```
Civil3DError
    ↓ raised by Civil3DClient method
    ↓ caught by tool async function
    ↓ returned as {"error": "Surface 'XYZ' not found."}
    ↓ sent to Claude as tool result
    ↓ Claude: "I couldn't find a surface named 'XYZ'. Available surfaces are: EG, FG."
```

---

## 9. Extending the server

To add a new tool group (e.g. Profiles, Corridors):

1. Add methods to `Civil3DClient` in `client.py`
2. Create `src/civil3d_mcp/tools_profiles.py` with a `register(mcp, client)` function
3. Import and call `tools_profiles.register(mcp, client)` in `server.py`
4. Add mock return values and tests in `tests/test_tools.py`

No changes to `pyproject.toml` or `setup.py` are needed — the package is
discovered automatically via `setuptools.packages.find`.

---

## 10. Civil 3D COM object model quick reference

```
AeccApplication  (root, via GetActiveObject)
└── ActiveDocument : AeccDocument
    ├── Name, FullName, Saved
    ├── GetVariable(sysvar)
    ├── ModelSpace : AcadModelSpace
    │   ├── AddLine(startPt, endPt) → AcadLine
    │   └── Add3DPoly(pointsArray)  → AcadEntity
    ├── CogoPoints : AeccCogoPointCollection
    │   ├── Add(x, y, z, desc) → pointId
    │   ├── Find(pointId)       → AeccCogoPoint
    │   ├── FindByPointNumber() → AeccCogoPoint
    │   └── Delete(pointNumber)
    ├── Surfaces : AeccSurfaceCollection
    │   └── [each] AeccTinSurface
    │       ├── Name, Description, StyleName
    │       ├── Statistics.MinimumElevation / MaximumElevation / MeanElevation
    │       ├── Statistics.NumberOfPoints / NumberOfTriangles / Area2D / Area3D
    │       └── FindElevationAtXY(x, y) → float
    └── AlignmentsSiteless : AeccAlignmentCollection
        └── [each] AeccAlignment
            ├── Name, Length, StartingStation, EndingStation
            ├── Entities : AeccAlignmentEntityCollection
            │   └── EntityAt(i) → AeccAlignmentEntity
            │       ├── EntityType, StartStation, EndStation, Length
            │       └── [curves] Radius, TangentLength, Delta
            └── StationOffset(x, y, &station, &offset)
```
