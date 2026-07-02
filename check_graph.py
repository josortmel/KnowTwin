import asyncio, httpx, json

async def check():
    async with httpx.AsyncClient(base_url="http://localhost:8080") as c:
        h = {"Authorization": "Bearer knowtwin_NuEZQAVbzTWp9LMZRKVWgfplCj9yoR2MRhdmexsBcrE"}
        r = await c.get("/graph/all?limit=200", headers=h)
        j = r.json()
        print(f"nodes: {j['node_count']}, edges: {j['edge_count']}")
        print(f"\nEdges ({len(j.get('edges', []))}):")
        for e in j.get("edges", []):
            print(f"  {e}")
        print(f"\nNodes with degree > 0:")
        for n in j.get("nodes", []):
            if n.get("degree", 0) > 0:
                print(f"  {n['name']} (degree={n['degree']})")

asyncio.run(check())
