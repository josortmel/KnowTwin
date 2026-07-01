import { Component, type ReactNode } from "react";

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
      return this.props.fallback ?? (
        <div className="p-4 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
          Something went wrong: {this.state.error.message}
        </div>
      );
    }
    return this.props.children;
  }
}
