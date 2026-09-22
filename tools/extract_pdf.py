import pdfplumber, json

PT_PER_FT = 36.0
PAGE = 864.0
def ft(v): return round(v / PT_PER_FT, 3)
def hexc(c):
    if c is None: return None
    if not isinstance(c,(list,tuple)): c=[c,c,c]
    if len(c)==1: c=[c[0]]*3
    return '#' + ''.join(f'{int(round(x*255)):02X}' for x in c[:3])

p = pdfplumber.open('/mnt/user-data/uploads/landscape-rendering-tool/backyard concept.pdf')
pg = p.pages[0]
R = {i:o for i,o in enumerate(pg.rects)}
C = {i:o for i,o in enumerate(pg.curves)}
L = {i:o for i,o in enumerate(pg.lines)}

def box(o):
    return dict(x=ft(o['x0']), y=ft(o['y0']), w=ft(o['x1']-o['x0']), h=ft(o['y1']-o['y0']))
def ctr(o):
    return dict(cx=ft((o['x0']+o['x1'])/2), cy=ft((o['y0']+o['y1'])/2))

objs = []
def add(z, oid, kind, src, geom, **kw):
    d = dict(z=z, id=oid, kind=kind, source=src)
    d.update(geom); d.update(kw); objs.append(d)

add(1,'site_circle','ellipse','curves[0]', dict(**ctr(C[0]), r=ft(432.0)),
    fill=None, stroke=hexc(C[0]['stroking_color']), stroke_w=ft(C[0]['linewidth']),
    note='Largest boundary. Diameter 24 ft, exactly inscribes the page.')
add(2,'hot_tub_pad','rect','rects[0]', box(R[0]),
    fill=hexc(R[0]['non_stroking_color']), stroke=None, stroke_w=0,
    note='9x9 ft light grey slab under the tub.')
add(3,'hot_tub','rounded_rect','curves[1]+curves[2]', dict(**box(C[1]), corner_r=ft(36.2)),
    fill=hexc(C[1]['non_stroking_color']), stroke=hexc(C[2]['stroking_color']), stroke_w=ft(C[2]['linewidth']),
    note='7x7 ft, 1 ft corner radius, centred on the pad.')
add(4,'planter_left','rect','rects[2]', box(R[2]),
    fill=hexc(R[2]['non_stroking_color']), stroke=hexc(R[2]['stroking_color']), stroke_w=ft(R[2]['linewidth']),
    note='4.5 x 1.5 ft green bed.')
add(5,'planter_right','rect','rects[3]', box(R[3]),
    fill=hexc(R[3]['non_stroking_color']), stroke=hexc(R[3]['stroking_color']), stroke_w=ft(R[3]['linewidth']),
    note='Mirror of planter_left.')
add(6,'bench_left','rect','rects[4]', box(R[4]),
    fill=hexc(R[4]['non_stroking_color']), stroke=hexc(R[4]['stroking_color']), stroke_w=ft(R[4]['linewidth']),
    note='4.5 x 2 ft wood, in front of planter_left.')
add(7,'bench_right','rect','rects[5]', box(R[5]),
    fill=hexc(R[5]['non_stroking_color']), stroke=hexc(R[5]['stroking_color']), stroke_w=ft(R[5]['linewidth']),
    note='Mirror of bench_left.')
add(8,'bench_left_seam','line','lines[2]',
    dict(x1=ft(L[2]['x0']), y1=ft(L[2]['y0']), x2=ft(L[2]['x1']), y2=ft(L[2]['y1'])),
    fill=None, stroke=hexc(L[2]['stroking_color']), stroke_w=ft(L[2]['linewidth']),
    note='Board seam; decoration, not a separate object.')
add(9,'bench_right_seam','line','lines[3]',
    dict(x1=ft(L[3]['x0']), y1=ft(L[3]['y0']), x2=ft(L[3]['x1']), y2=ft(L[3]['y1'])),
    fill=None, stroke=hexc(L[3]['stroking_color']), stroke_w=ft(L[3]['linewidth']),
    note='Board seam.')
add(10,'deck_rail_right','rect','rects[6]', box(R[6]),
    fill=hexc(R[6]['non_stroking_color']), stroke=hexc(R[6]['stroking_color']), stroke_w=ft(R[6]['linewidth']),
    note='Part of the U-shaped wood surround.')
add(11,'deck_rail_left','rect','rects[7]', box(R[7]),
    fill=hexc(R[7]['non_stroking_color']), stroke=hexc(R[7]['stroking_color']), stroke_w=ft(R[7]['linewidth']),
    note='Part of the U-shaped wood surround.')
add(12,'deck_rail_bottom','rect','rects[8]', box(R[8]),
    fill=hexc(R[8]['non_stroking_color']), stroke=hexc(R[8]['stroking_color']), stroke_w=ft(R[8]['linewidth']),
    note='Closes the U on the south side.')
add(13,'fence_enclosure','rect_outline','rects[9]', box(R[9]),
    fill=None, stroke=hexc(R[9]['stroking_color']), stroke_w=ft(R[9]['linewidth']),
    note='14 x 10 ft unfilled outline enclosing the whole tub area.')
add(14,'stone_a','hexagon','curves[3]', dict(**ctr(C[3]), w=ft(59.2), h=ft(54.1)),
    fill=hexc(C[3]['non_stroking_color']), stroke=None, stroke_w=0,
    note='Regular hexagon, flat-top, ~1.6 ft across.')
add(15,'stone_b','hexagon','curves[4]', dict(**ctr(C[4]), w=ft(59.2), h=ft(54.1)),
    fill=hexc(C[4]['non_stroking_color']), stroke=None, stroke_w=0,
    note='Same hexagon, offset up and right.')
add(16,'back_fence','rect','rects[10]', box(R[10]),
    fill=hexc(R[10]['non_stroking_color']), stroke=hexc(R[10]['stroking_color']), stroke_w=ft(R[10]['linewidth']),
    note='20 ft run along the north edge.')
add(17,'back_fence_seam','line','lines[4]',
    dict(x1=ft(L[4]['x0']), y1=ft(L[4]['y0']), x2=ft(L[4]['x1']), y2=ft(L[4]['y1'])),
    fill=None, stroke=hexc(L[4]['stroking_color']), stroke_w=ft(L[4]['linewidth']),
    note='Rail line inside back_fence.')
add(18,'fire_circle','ellipse','curves[5]', dict(**ctr(C[5]), r=ft(216.0)),
    fill=None, stroke=hexc(C[5]['stroking_color']), stroke_w=ft(C[5]['linewidth']),
    note='12 ft diameter; runs off the bottom of the page.')
add(19,'fire_feature','ellipse','curves[6]', dict(**ctr(C[6]), rx=ft(36.45), ry=ft(34.4)),
    fill=hexc(C[6]['non_stroking_color']), stroke=None, stroke_w=0,
    note='~2 ft; NOT concentric with fire_circle (offset 0.22 ft E, 0.76 ft N).')

doc = dict(
    source_pdf='backyard concept.pdf',
    creator='Adobe Illustrator 30.6 (Macintosh)',
    page_pt=[864.0, 864.0], scale_pt_per_ft=PT_PER_FT,
    extent_ft=[24.0, 24.0],
    origin='bottom-left of page, x east, y north, units feet',
    scale_reference='Scale badge rects[1] is 72.0 pt wide and labelled 2 ft',
    excluded=['rects[1] scale badge', 'lines[0..1] scale arrows', 'text "< 2’ >"'],
    objects=objs)
json.dump(doc, open('/home/claude/out/objects.json','w'), indent=2)
print(json.dumps(doc['objects'], indent=1)[:200])
print("objects:", len(objs))
