import sys, json, formulas
p, cases = sys.argv[1], json.load(open(sys.argv[2]))
xl=formulas.ExcelModel().loads(p).finish(); sol=xl.calculate()
import os
res={}
for k,v in sol.items():
    ks=str(k).upper()
    for c,f,e in cases:
        if ks.endswith('!'+c): 
            val=v.value[0][0] if hasattr(v,'value') else v
            res[c]=val
for c,f,e in cases:
    got=res.get(c); print(f'{c:4} {f:32} expected={e!r:14} formulas={got!r}')
