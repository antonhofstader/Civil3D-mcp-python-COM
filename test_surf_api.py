import win32com.client as w32
import pythoncom
from civil3d_mcp.client import Civil3DClient
import array

out = []

try:
    c = Civil3DClient()
    c.connect()

    # Get TypeInfo for AddPointMultiple
    cd = c._acad.GetInterfaceObject("AeccXLand.AeccTinCreationData.13.7")
    cd.Name = "__FullWorkflowTest__"
    cd.Layer = "0"
    cd.BaseLayer = "0"
    cd.Style = "Border Only"
    surf = c._doc.Surfaces.AddTinSurface(cd)

    # Get AddPointMultiple TypeInfo
    try:
        ti = surf._oleobj_.GetTypeInfo()
        ta = ti.GetTypeAttr()
        for fi in range(ta.cFuncs):
            fd = ti.GetFuncDesc(fi)
            fname = ti.GetNames(fd.memid)[0]
            if fname in ("AddPointMultiple", "AddPoint"):
                out.append(f"func: {fname} memid={fd.memid} args={fd.args}")
    except Exception as ex:
        out.append("TypeInfo err: " + str(ex)[:100])

    # Probe Breaklines collection
    blines = surf.Breaklines
    out.append("Breaklines dir: " + str([a for a in dir(blines) if not a.startswith("_")]))

    # Get TypeInfo for Breaklines.Add
    try:
        ti2 = blines._oleobj_.GetTypeInfo()
        ta2 = ti2.GetTypeAttr()
        for fi in range(ta2.cFuncs):
            fd2 = ti2.GetFuncDesc(fi)
            fname2 = ti2.GetNames(fd2.memid)[0]
            if fname2 == "Add":
                out.append(f"Breaklines.Add args: {fd2.args}")
                break
    except Exception as ex:
        out.append("Breaklines TypeInfo err: " + str(ex)[:100])

    # Find the closed polyline
    ms = c._acad.ActiveDocument.ModelSpace
    pline_obj = None
    for i in range(ms.Count):
        try:
            raw = ms.Item(i)
            obj = w32.Dispatch(raw)
            oname = getattr(obj, "ObjectName", "")
            if "Polyline" in oname and getattr(obj, "Closed", False) and pline_obj is None:
                pline_obj = obj
        except:
            pass

    if not pline_obj:
        coords = array.array('d', [0,0,0, 100,0,0, 100,100,0, 0,100,0])
        pline = c._acad.ActiveDocument.ModelSpace.AddPolyline(coords)
        pline.Closed = True
        pline_obj = w32.Dispatch(pline)
        out.append("Created polyline: " + pline_obj.Handle)

    out.append("polyline: " + str(pline_obj.Handle))

    # Try AddPointMultiple with different arg formats
    coords_raw = pline_obj.Coordinates
    n = len(coords_raw) // 2
    pts_flat = []
    for i in range(n):
        pts_flat.extend([coords_raw[i*2], coords_raw[i*2+1], 0.0])

    for arr_type in [
        array.array('d', pts_flat),
        tuple(pts_flat),
        pts_flat,
        tuple((coords_raw[i*2], coords_raw[i*2+1], 0.0) for i in range(n)),
    ]:
        try:
            surf.AddPointMultiple(arr_type)
            out.append("AddPointMultiple OK with " + type(arr_type).__name__)
            break
        except Exception as ex:
            out.append("AddPointMultiple " + type(arr_type).__name__ + " FAIL: " + str(ex.args[1] if len(ex.args)>1 else ex)[:60])

    # Try adding breakline
    try:
        blines = surf.Breaklines
        for args in [
            (pline_obj, "Outer", 0, False, 0.0),
            (pline_obj, "Outer", 0),
            (pline_obj, "Outer"),
            (pline_obj,),
        ]:
            try:
                result = blines.Add(*args)
                out.append(f"Breaklines.Add({len(args)} args) SUCCESS!")
                break
            except Exception as ex:
                out.append(f"Breaklines.Add({len(args)}) err: " + str(ex.args[:3] if ex.args else ex)[:120])
    except Exception as ex:
        out.append("breaklines err: " + str(ex)[:100])

    surf.Erase()
    out.append("Erased")
except Exception as ex:
    out.append("TOP ERR: " + str(ex)[:300])

with open("surf_api_out.txt", "w") as f:
    f.write("\n".join(out))
