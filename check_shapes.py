import asyncio, httpx, json

KEY = "knowtwin_NuEZQAVbzTWp9LMZRKVWgfplCj9yoR2MRhdmexsBcrE"

async def check():
    async with httpx.AsyncClient(base_url="http://localhost:8080") as c:
        h = {"Authorization": f"Bearer {KEY}"}

        # Q1: Claims filters
        print("=== Q1: GET /claims filters ===")
        r = await c.get("/claims?project_id=1&limit=1", headers=h)
        if r.status_code == 200:
            j = r.json()
            print(f"response keys: {list(j.keys())}")
            if j.get("items"):
                print(f"item keys: {list(j['items'][0].keys())}")
        for p in ["corroboration_level=single_source", "dispute_state=disputed",
                   "source_type=interview", "subject_entity=Banco+Norte"]:
            r2 = await c.get(f"/claims?project_id=1&{p}&limit=1", headers=h)
            total = r2.json().get("total", "?") if r2.status_code == 200 else r2.status_code
            print(f"  ?{p} -> {r2.status_code} total={total}")

        # Q2: Attention inbox item shapes
        print("\n=== Q2: attention-inbox/details ===")
        for dc in ["pending_disputes", "pending_deletions"]:
            r = await c.get(f"/admin/attention-inbox/details?decision_class={dc}&limit=1", headers=h)
            if r.status_code == 200:
                j = r.json()
                items = j.get("items", [])
                if items:
                    print(f"{dc}: item keys = {list(items[0].keys())}")
                    print(f"  sample: {json.dumps(items[0], default=str)[:200]}")
                else:
                    print(f"{dc}: 0 items")

        # Q3: Graph node/edge shape
        print("\n=== Q3: /graph/all shapes ===")
        r = await c.get("/graph/all?limit=5", headers=h)
        if r.status_code == 200:
            j = r.json()
            nodes = j.get("nodes", [])
            edges = j.get("edges", [])
            if nodes:
                print(f"node keys: {list(nodes[0].keys())}")
                print(f"  sample: {json.dumps(nodes[0], default=str)[:200]}")
            print(f"edges count: {len(edges)}")
            if edges:
                print(f"edge keys: {list(edges[0].keys())}")
                print(f"  sample: {json.dumps(edges[0], default=str)[:200]}")

        # Q4: Entity dictionary shape
        print("\n=== Q4: entity-dictionary ===")
        r = await c.get("/admin/entity-dictionary", headers=h)
        if r.status_code == 200:
            j = r.json()
            if j:
                print(f"entry keys: {list(j[0].keys())}")
                print(f"  sample: {json.dumps(j[0], default=str)[:200]}")

        # Q5: Document detail
        print("\n=== Q5: document detail ===")
        docs = (await c.get("/documents?project_id=1", headers=h)).json()
        if docs:
            did = docs[0]["id"]
            r = await c.get(f"/documents/{did}", headers=h)
            if r.status_code == 200:
                print(f"doc keys: {list(r.json().keys())}")
            r2 = await c.get(f"/documents/{did}/chunks?limit=1", headers=h)
            if r2.status_code == 200:
                cj = r2.json()
                print(f"chunks response keys: {list(cj.keys())}")
                if cj.get("chunks"):
                    print(f"chunk keys: {list(cj['chunks'][0].keys())}")

        # Q7: Interview session shape
        print("\n=== Q7: interview sessions ===")
        r = await c.get("/interviews?project_id=1", headers=h)
        if r.status_code == 200:
            j = r.json()
            if isinstance(j, list) and j:
                print(f"session keys: {list(j[0].keys())}")
                print(f"  sample: {json.dumps(j[0], default=str)[:200]}")

asyncio.run(check())
