import { useState } from "react";
import { GlassCard } from "../components/GlassCard";
import { Panel, PanelState } from "../components/Panel";
import { Button } from "../components/Button";
import { Chip } from "../components/Chip";
import { Dot } from "../components/Dot";
import { Toggle } from "../components/Toggle";
import { ThemeToggle } from "../components/ThemeToggle";
import { SearchField } from "../components/SearchField";
import { StatusPill } from "../components/StatusPill";
import { StatCard } from "../components/StatCard";
import { BrandLockup } from "../components/BrandMark";
import { CorroborationBadge } from "../components/CorroborationBadge";
import { CoverageStateBadge } from "../components/CoverageStateBadge";
import { DisputeBadge } from "../components/DisputeBadge";
import { TrustTierBadge } from "../components/TrustTierBadge";
import { SensitivityBadge } from "../components/SensitivityBadge";
import { StateBadge } from "../components/StateBadge";
import { Loading } from "../components/Loading";
import { EmptyState } from "../components/EmptyState";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { ConfirmDialog } from "../components/ConfirmDialog";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-3 py-2">
      <span className="w-40 flex-none font-mono text-[10px] uppercase tracking-[0.12em] text-ink-3">{label}</span>
      <div className="flex flex-wrap items-center gap-3">{children}</div>
    </div>
  );
}

function Boom(): React.ReactNode {
  throw new Error("Demo error caught by the boundary");
}

// Temporary kit gallery (Tarea #8). Reachable at /kit, bypasses auth. Every
// component in isolation for adversarial-visual review against DESIGN.md §3/§7.
export function KitGallery() {
  const [on, setOn] = useState(true);
  const [q, setQ] = useState("");
  const [confirm, setConfirm] = useState(false);

  return (
    <div className="min-h-screen p-8">
      <header className="mx-auto mb-6 flex max-w-5xl items-center justify-between">
        <BrandLockup />
        <div className="flex items-center gap-3">
          <StatusPill status="online" latencyMs={42} />
          <ThemeToggle />
        </div>
      </header>

      <div className="mx-auto grid max-w-5xl grid-cols-1 gap-4 md:grid-cols-2">
        <Panel title="Buttons">
          <div className="flex flex-col gap-3">
            <Row label="variants">
              <Button variant="default">Default</Button>
              <Button variant="primary">Approve</Button>
              <Button variant="tint">Filter</Button>
              <Button variant="danger">Reject</Button>
            </Row>
            <Row label="states">
              <Button variant="primary" loading>
                Saving
              </Button>
              <Button variant="default" disabled>
                Disabled
              </Button>
            </Row>
          </div>
        </Panel>

        <Panel title="Chips & Dots">
          <div className="flex flex-col gap-3">
            <Row label="chips">
              <Chip>mono</Chip>
              <Chip tone="hot">live</Chip>
            </Row>
            <Row label="dots">
              <Dot s="on" />
              <Dot s="ok" />
              <Dot s="alert" />
              <Dot s="idle" />
              <Dot s="on" anim="blink" />
              <Dot s="ok" anim="pulse" />
            </Row>
          </div>
        </Panel>

        <Panel title="Controls">
          <div className="flex flex-col gap-3">
            <Row label="toggle">
              <Toggle on={on} onChange={setOn} label="Demo toggle" />
              <span className="font-mono text-[11px] text-ink-2">{on ? "ON" : "OFF"}</span>
            </Row>
            <Row label="theme">
              <ThemeToggle />
            </Row>
            <Row label="search">
              <SearchField value={q} onChange={setQ} placeholder="Search claims…" resultCount={34} />
            </Row>
          </div>
        </Panel>

        <Panel title="Stat cards">
          <div className="grid grid-cols-3 gap-3">
            <StatCard label="Claims" value="34" />
            <StatCard label="Disputed" value="16" accent />
            <StatCard label="Coverage" value="46.3" unit="%" sub="Banco Norte" />
          </div>
        </Panel>

        <Panel title="Corroboration §7.1">
          <div className="flex flex-col gap-2">
            {["draft", "single_source", "corroborated", "corroborated_by_employee", "validated", "rejected"].map((l) => (
              <CorroborationBadge key={l} level={l} />
            ))}
          </div>
        </Panel>

        <Panel title="Coverage §7.2">
          <div className="flex flex-col gap-2">
            {["unknown", "partial", "clear", "disputed", "validated", "stale"].map((s) => (
              <CoverageStateBadge key={s} state={s} />
            ))}
          </div>
        </Panel>

        <Panel title="Dispute §7.3 · Trust & Sensitivity §7.4">
          <div className="flex flex-col gap-3">
            <Row label="dispute">
              <DisputeBadge state="disputed" />
              <DisputeBadge state="resolved_in_favor" />
              <DisputeBadge state="resolved_against" />
            </Row>
            <Row label="trust tier">
              <TrustTierBadge tier={0} />
              <TrustTierBadge tier={1} />
              <TrustTierBadge tier={2} />
            </Row>
            <Row label="sensitivity">
              <SensitivityBadge level="public" />
              <SensitivityBadge level="team" />
              <SensitivityBadge level="restricted" />
            </Row>
            <Row label="doc status">
              <StateBadge state="indexed" />
              <StateBadge state="processing" />
              <StateBadge state="failed" />
            </Row>
          </div>
        </Panel>

        <Panel title="States">
          <div className="flex flex-col gap-2">
            <PanelState loading>x</PanelState>
            <Loading message="Loading claims…" />
            <EmptyState message="No disputes to resolve" />
            <ErrorBoundary>
              <Boom />
            </ErrorBoundary>
            <Button variant="danger" onClick={() => setConfirm(true)}>
              Open confirm dialog
            </Button>
          </div>
        </Panel>

        <GlassCard className="p-5 md:col-span-2">
          <div className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-2">Plain GlassCard</div>
          <p className="mt-2 text-[13px] text-ink-2">
            Move the cursor across this card — the specular highlight tracks the pointer (§2.5). Hover lifts it.
          </p>
        </GlassCard>
      </div>

      <ConfirmDialog
        open={confirm}
        title="Reject this claim?"
        message="The claim will be soft-deleted and its embedding removed. This can be audited later."
        confirmLabel="Reject"
        destructive
        onConfirm={() => setConfirm(false)}
        onCancel={() => setConfirm(false)}
      />
    </div>
  );
}
