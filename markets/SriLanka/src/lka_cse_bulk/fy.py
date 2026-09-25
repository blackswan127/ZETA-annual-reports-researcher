import re

def resolve_fy(record):
 text=' '.join(str(record.get(k,'')) for k in ('fileText','title','name','description','period','periodEnd','year','financialYear'))
 text=re.sub(r'\s+',' ',text)
 m=re.search(r'\bFY\s*20(\d{2})\b',text,re.I)
 if m:return 2000+int(m.group(1)),1.0,'explicit_fy'
 m=re.search(r'\b(20\d{2})\s*[-/]\s*(20\d{2}|\d{2})\b',text)
 if m:
  a=int(m.group(1)); b=int(m.group(2)); b=(a//100)*100+b if b<100 else b
  if a<=b<=a+1:return b,.98,'year_range'
 m=re.search(r'\b(?:annual\s+report|integrated\s+annual\s+report)[^\d]{0,15}(20\d{2})\b',text,re.I)
 if m:return int(m.group(1)),.96,'title_year'
 years=[int(y) for y in re.findall(r'\b(20(?:1[0-9]|2[0-9]))\b',text)]
 if years:return max(years),.72,'generic_year'
 return None,0.0,'unresolved'
