import { useSyncExternalStore } from "react";

// Minimal toast emitter (ported from EcoDB's Toasts, external-store variant — no
// zustand, same pattern as lib/theme.ts). Any module can pushToast(); <Toasts/>
// in the shell renders them.
export type ToastTone = "success" | "error" | "info";

export interface Toast {
  id: string;
  message: string;
  tone: ToastTone;
  action?: { label: string; onClick: () => void };
}

let toasts: Toast[] = [];
const listeners = new Set<() => void>();
let seq = 0;

function emit() {
  for (const l of listeners) l();
}

export function pushToast(
  message: string,
  opts?: { tone?: ToastTone; durationMs?: number; action?: Toast["action"] },
): string {
  const id = `t${Date.now()}_${seq++}`;
  toasts = [...toasts, { id, message, tone: opts?.tone ?? "success", action: opts?.action }];
  emit();
  const duration = opts?.durationMs ?? (opts?.action ? 7000 : 5000);
  if (duration > 0) setTimeout(() => dismissToast(id), duration);
  return id;
}

export function dismissToast(id: string) {
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}

export function useToasts(): Toast[] {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => toasts,
    () => toasts,
  );
}
