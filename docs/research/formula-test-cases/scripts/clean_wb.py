import sys, openpyxl, formulas
src,dst=sys.argv[1],sys.argv[2]
wbf=openpyxl.load_workbook(src); wbv=openpyxl.load_workbook(src, data_only=True); bad=0
for ws in wbf.worksheets:
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value,str) and c.value.startswith('='):
                try: formulas.Parser().ast(c.value)
                except Exception: c.value=wbv[ws.title][c.coordinate].value; bad+=1
wbf.save(dst); print('unparseable formulas replaced by cached value:',bad)
