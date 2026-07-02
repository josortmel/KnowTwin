import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "../../lib/api";
import { GlassCard } from "../../components/GlassCard";
import { Button } from "../../components/Button";
import { pushToast } from "../../lib/toast";

const FIELD_STYLE = {
  background: "var(--field-bg)",
  boxShadow: "inset 0 1px 3px var(--inset), inset 0 0 0 1px var(--card-hairline)",
};
const FIELD = "rounded-md px-2.5 py-1.5 font-body text-[13px] text-ink-1 outline-none placeholder:text-ink-3";

export function ProcessSetupForm() {
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [accounts, setAccounts] = useState("");
  const qc = useQueryClient();

  const create = useMutation({
    mutationFn: () =>
      post("/projects", {
        name: `${name} Offboarding`,
        employee_name: name,
        role,
        accounts: accounts.split(",").map((a) => a.trim()).filter(Boolean),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      setName("");
      setRole("");
      setAccounts("");
      pushToast("Offboarding process created", { tone: "success" });
    },
    onError: (e) => pushToast(`Failed: ${e instanceof Error ? e.message : String(e)}`, { tone: "error" }),
  });

  return (
    <GlassCard className="p-card-lg">
      <h3 className="mb-3 font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-2">New Offboarding Process</h3>
      <div className="grid grid-cols-2 gap-3">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Employee name" className={FIELD} style={FIELD_STYLE} />
        <input value={role} onChange={(e) => setRole(e.target.value)} placeholder="Role" className={FIELD} style={FIELD_STYLE} />
        <input
          value={accounts}
          onChange={(e) => setAccounts(e.target.value)}
          placeholder="Accounts (comma-separated)"
          className={`${FIELD} col-span-2`}
          style={FIELD_STYLE}
        />
      </div>
      <Button variant="primary" onClick={() => create.mutate()} disabled={!name} loading={create.isPending} className="mt-3">
        Create Process
      </Button>
    </GlassCard>
  );
}
