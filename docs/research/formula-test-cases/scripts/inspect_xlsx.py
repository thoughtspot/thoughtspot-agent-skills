import sys, openpyxl
from collections import Counter
p=sys.argv[1]
wbf=openpyxl.load_workbook(p, data_only=False); wbv=openpyxl.load_workbook(p, data_only=True)
for ws in wbf.worksheets:
    wv=wbv[ws.title]; n=0; withval=0; funcs=Counter(); ex=[]
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value,str) and c.value.startswith('='):
                n+=1; v=wv[c.coordinate].value
                if v is not None: withval+=1
                import re
                for f in re.findall(r'([A-Z][A-Z0-9\.]+)\(', c.value): funcs[f]+=1
                if len(ex)<4: ex.append((c.coordinate,c.value,v))
    print(ws.title, ws.max_row, ws.max_column, 'formulas',n,'cached',withval,'distinct funcs',len(funcs))
    print('  ',ex)
