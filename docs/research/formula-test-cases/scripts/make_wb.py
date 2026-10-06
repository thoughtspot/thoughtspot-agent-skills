import sys, datetime as dt, openpyxl
wb=openpyxl.Workbook(); ws=wb.active; ws.title='S'
ws['A2']=dt.date(2012,10,1); ws['A3']=dt.date(2013,3,1); ws['A4']=dt.date(2012,11,22); ws['A5']=dt.date(2012,12,4); ws['A6']=dt.date(2013,1,21)
ws['B1']=1234.5678; ws['B2']=-2.5; ws['B3']=2.5; ws['B4']=None; ws['B5']=0; ws['B6']='text'
ws['C1']=dt.date(2026,10,4)
cases=[ # (cell, formula, expected per Excel docs/semantics)
 ('D1','=NETWORKDAYS(A2,A3)',110),('D2','=NETWORKDAYS(A2,A3,A4)',109),('D3','=NETWORKDAYS(A2,A3,A4:A6)',107),
 ('D4','=ROUND(B1,2)',1234.57),('D5','=ROUND(B2,0)',-3),('D6','=ROUND(B3,0)',3),
 ('D7','=WEEKDAY(C1)',1),('D8','=WEEKDAY(C1,2)',7),('D9','=DATEDIF(A2,A3,"m")',5),
 ('D10','=AVERAGE(B2:B6)',0.0),('D11','=COUNT(B1:B6)',4),('D12','=COUNTA(B1:B6)',5),
 ('D13','=B4+1',1),('D14','=B4&"x"','x'),('D15','=IFERROR(1/B5,-1)',-1),('D16','=1/B5','#DIV/0!'),
 ('D17','=TEXT(C1,"yyyy-mm-dd")','2026-10-04'),('D18','=MOD(-7,3)',2),('D19','=INT(-2.5)',-3),
 ('D20','=EOMONTH(A2,1)',41243),('D21','=YEARFRAC(A2,A3,1)',None),('D22','=NETWORKDAYS.INTL(A2,A3,11)',None),
 ('D23','=B6*1','#VALUE!'),('D24','=0.1+0.2=0.3',True),('D25','=SUMPRODUCT((B1:B3>0)*B1:B3)',1237.0678),
 ('D26','=ISBLANK(B4)',True),('D27','=MEDIAN(B1:B6)',1.25),('D28','=STDEV(B1:B3)',None),
]
for c,f,e in cases: ws[c]=f
import json; json.dump([(c,f,e) for c,f,e in cases], open(sys.argv[2],'w'))
wb.save(sys.argv[1])
