import sys, xml.etree.ElementTree as ET
NS={'table':'urn:oasis:names:tc:opendocument:xmlns:table:1.0','office':'urn:oasis:names:tc:opendocument:xmlns:office:1.0','text':'urn:oasis:names:tc:opendocument:xmlns:text:1.0'}
T='{%s}'%NS['table']; O='{%s}'%NS['office']
for p in sys.argv[1:]:
    root=ET.parse(p).getroot()
    for t in root.iter(T+'table'):
        name=t.get(T+'name'); rows=[]
        for r in t.iter(T+'table-row'):
            cells=[]
            for c in r.findall(T+'table-cell'):
                rep=int(c.get(T+'number-columns-repeated','1'))
                f=c.get(T+'formula'); v=c.get(O+'value') or c.get(O+'date-value') or c.get(O+'boolean-value') or c.get(O+'string-value')
                txt=''.join(c.itertext())
                cells += [(f, v if v is not None else txt)]*min(rep,3)
            rows.append(cells)
        nform=sum(1 for r in rows for c in r if c[0])
        print(p.split('/')[-1], name, 'rows',len(rows),'formula cells',nform)
        if name not in ('Sheet1',):
            for r in rows[:4]: print('   ',[c for c in r[:5]])
