from lxml import html

with open('/tmp/staff_output.html', 'r', encoding='utf-8') as f:
    text = f.read()

try:
    doc = html.fromstring(text)
    print("Parsed OK")
    # Let's see where tbody is
    tbodies = doc.xpath('//tbody')
    if tbodies:
        print("<tbody> found. Children:", len(tbodies[0]))
        for child in tbodies[0]:
            print(child.tag)
    else:
        print("No tbody!")
        
    tables = doc.xpath('//table')
    if tables:
        print("<table> found. Children:")
        for child in tables[0]:
            print(child.tag)
            
except Exception as e:
    print("Error:", e)
