import sys, os, json, xml.etree.ElementTree as ET
T='{urn:oasis:names:tc:opendocument:xmlns:table:1.0}'; O='{urn:oasis:names:tc:opendocument:xmlns:office:1.0}'
root_dir=sys.argv[1]; out=[]; tot=0; per={}
for sub in sorted(os.listdir(root_dir)):
    d=os.path.join(root_dir,sub)
    if not os.path.isdir(d): continue
    n=0
    for fn in sorted(os.listdir(d)):
        try: root=ET.parse(os.path.join(d,fn)).getroot()
        except Exception as e: print('ERR',fn,e); continue
        for t in root.iter(T+'table'):
            rows=list(t.iter(T+'table-row'))
            if not rows: continue
            hdr=[''.join(c.itertext()).strip() for c in rows[0].findall(T+'table-cell')]
            if hdr[:2]!=['Function','Expected']: continue
            for r in rows[1:]:
                cs=r.findall(T+'table-cell')
                if len(cs)<2 or not cs[0].get(T+'formula'): continue
                exp=cs[1]; ev=exp.get(O+'value') or exp.get(O+'date-value') or exp.get(O+'boolean-value') or ''.join(exp.itertext()).strip()
                if exp.get(T+'formula'): ev=None  # expected computed, not literal
                n+=1
                out.append({'dialect':'openformula','file':f'{sub}/{fn}','formula':cs[0].get(T+'formula'),'expected':ev,'expected_type':exp.get(O+'value-type')})
    per[sub]=n; tot+=n
print(per, 'total', tot)
lit=sum(1 for o in out if o['expected'] not in (None,''))
print('literal expected', lit)
json.dump(out, open(sys.argv[2],'w'), indent=0)
