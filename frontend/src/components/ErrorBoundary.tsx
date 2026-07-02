import { Component, type ReactNode } from "react";
import { Dot } from "./Dot";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        this.props.fallback ?? (
          <div
            className="flex items-start gap-2 rounded-md p-4"
            style={{
              background: "color-mix(in srgb, var(--red) 8%, transparent)",
              boxShadow: "inset 0 0 0 1px color-mix(in srgb, var(--red) 25%, transparent)",
            }}
          >
            <Dot s="alert" glow className="mt-[3px]" />
            <div>
              <div className="font-body text-[13px] font-semibold text-ink-1">Something went wrong</div>
              <div className="mt-0.5 font-mono text-[12px] leading-relaxed text-ink-2">{this.state.error.message}</div>
            </div>
          </div>
        )
      );
    }
    return this.props.children;
  }
}
