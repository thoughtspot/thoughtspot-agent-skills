import sys, math, datetime, collections, re, openpyxl, formulas
p=sys.argv[1]; pc=sys.argv[2]
wbf=openpyxl.load_workbook(pc); wbv=openpyxl.load_workbook(pc, data_only=True)
cached={}
for ws in wbf.worksheets:
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value,str) and c.value.startswith('='):
                cached[(ws.title.upper(), c.coordinate)]=(c.value, wbv[ws.title][c.coordinate].value)
xl=formulas.ExcelModel().loads(p).finish(); sol=xl.calculate()
got={}
for k,v in sol.items():
    m=re.match(r"'?\[[^\]]+\](.+?)'?!([A-Z]+[0-9]+)$", str(k).upper())
    if m:
        try: got[(m.group(1),m.group(2))]=v.value[0][0]
        except Exception: got[(m.group(1),m.group(2))]=v
def norm(x):
    if isinstance(x,(datetime.datetime,datetime.date,datetime.time)): return None
    s=str(x)
    try: return float(x)
    except Exception: return s.upper()
agree=dis=miss=skip=0; ex=[]; byfunc=collections.Counter()
for key,(f,cv) in cached.items():
    if cv is None: skip+=1; continue
    if key not in got: miss+=1; continue
    a,b=norm(cv),norm(got[key])
    if a is None: skip+=1; continue
    ok = (isinstance(a,float) and isinstance(b,float) and (a==b or abs(a-b)<=1e-9*max(1,abs(a)))) or a==b
    if ok: agree+=1
    else:
        dis+=1; cat=("NAME" if "NAME" in str(got[key]) else ("cache_VALUE_range" if str(cv)=="#VALUE!" else "other")); byfunc["CAT:"+cat]+=1; fn=(re.findall(r'([A-Z][A-Z0-9\.]+)\(',f) or ['op'])[0]; byfunc[fn]+=1
        if cat=="other" and len(ex)<25: ex.append((key,f,cv,got[key]))
print('formula cells',len(cached),'agree',agree,'disagree',dis,'not evaluated',miss,'skipped(no cache/date)',skip)
print('disagree by first function',byfunc.most_common(15))
for e in ex: print('  ',e)
