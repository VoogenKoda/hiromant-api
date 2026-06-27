import os
import psycopg2

def get_valid_attributes():
    url = os.environ.get("DATABASE_URL")
    if not url:
        return {}
    url = url.replace('"', '')
    conn = psycopg2.connect(url)
    cur = conn.cursor()
    cur.execute('''
        SELECT c.canonical_name, cl.attribute_value 
        FROM claim cl 
        JOIN concept c ON cl.concept_id = c.id;
    ''')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    
    schema = {}
    for r in rows:
        c_name = r[0]
        a_val = r[1]
        if c_name not in schema:
            schema[c_name] = set()
        schema[c_name].add(a_val)
        
    return {k: list(v) for k, v in schema.items()}

def fetch_claims(features):
    url = os.environ.get("DATABASE_URL")
    if not url:
        return "", 0
    url = url.replace('"', '')
    conn = psycopg2.connect(url)
    cursor = conn.cursor()
    
    knowledge_context = ""
    total_claims = 0
    
    for f in features:
        c_name = f.concept_canonical_name.lower().strip()
        a_val = f.attribute_value.lower().strip()
        search_val = f"%{a_val.replace('_', '%')}%"
        
        cursor.execute("""
            SELECT cl.claim_text, cl.normalized_interpretation
            FROM claim cl
            JOIN concept c ON cl.concept_id = c.id
            WHERE c.canonical_name LIKE %s AND cl.attribute_value LIKE %s
            LIMIT 3
        """, (f"%{c_name}%", search_val))
        
        rows = cursor.fetchall()
        if rows:
            knowledge_context += f"\nLeitud reeglid pildilt tuvastatud tunnusele [{f.concept_canonical_name}: {f.attribute_name} = {f.attribute_value}]:\n"
            for row in rows:
                knowledge_context += f"- Tähendus: {row[1]}\n  Allika tekst: {row[0]}\n"
                total_claims += 1
                
    cursor.close()
    conn.close()
    return knowledge_context, total_claims
