import requests

html = requests.get('https://wedrink-production.up.railway.app/stock_input').text
if 'function renderTable(initialValues = null)' in html:
    print("DEPLOYED!")
else:
    print("NOT DEPLOYED!")
    
if "initialValues[p.id]" in html:
    print("INITIAL VALUES IN HTML")
else:
    print("NO INITIAL VALUES IN HTML")
