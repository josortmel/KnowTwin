import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "../../lib/api";

export function ProcessSetupForm() {
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [accounts, setAccounts] = useState("");
  const qc = useQueryClient();

  const create = useMutation({
    mutationFn: () => post("/projects", {
      name: `${name} Offboarding`,
      employee_name: name, role, accounts: accounts.split(",").map(a => a.trim()).filter(Boolean),
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["projects"] }); setName(""); setRole(""); setAccounts(""); },
  });

  return (
    <div className="border rounded p-4">
      <h3 className="font-semibold mb-3">New Offboarding Process</h3>
      <div className="grid grid-cols-2 gap-3">
        <input value={name} onChange={e => setName(e.target.value)} placeholder="Employee name"
          className="border rounded px-2 py-1 text-sm" />
        <input value={role} onChange={e => setRole(e.target.value)} placeholder="Role"
          className="border rounded px-2 py-1 text-sm" />
        <input value={accounts} onChange={e => setAccounts(e.target.value)}
          placeholder="Accounts (comma-separated)" className="border rounded px-2 py-1 text-sm col-span-2" />
      </div>
      <button onClick={() => create.mutate()} disabled={!name || create.isPending}
        className="mt-3 px-4 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50">
        {create.isPending ? "Creating..." : "Create Process"}
      </button>
      {create.isError && <p className="text-red-500 text-xs mt-1">{String(create.error)}</p>}
    </div>
  );
}
