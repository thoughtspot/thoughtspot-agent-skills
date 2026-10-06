import sys, json
from pycel import ExcelCompiler
p, cases = sys.argv[1], json.load(open(sys.argv[2]))
xl=ExcelCompiler(filename=p)
for c,f,e in cases:
    try: got=xl.evaluate('S!'+c)
    except Exception as ex: got='EXC:'+type(ex).__name__+':'+str(ex)[:60]
    print(f'{c:4} {f:32} expected={e!r:14} pycel={got!r}')
