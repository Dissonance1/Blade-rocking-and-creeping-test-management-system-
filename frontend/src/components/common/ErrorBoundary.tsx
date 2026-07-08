import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info);
  }

  override render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="min-h-screen bg-slate-900 flex items-center justify-center text-white px-4">
          <div className="text-center max-w-md w-full">
            <h1 className="text-xl sm:text-2xl font-bold mb-2">Something went wrong</h1>
            <p className="text-slate-400 text-sm mb-4 break-words">{this.state.error?.message}</p>
            <button
              className="inline-flex items-center justify-center min-h-11 px-4 py-2 bg-orange-600 hover:bg-orange-500 rounded-md text-sm font-medium"
              onClick={() => this.setState({ hasError: false, error: null })}
            >
              Try Again
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
