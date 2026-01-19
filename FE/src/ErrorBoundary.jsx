import React from "react";

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    console.error("❌ SimulatorPage 렌더링 중 오류:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            padding: 32,
            color: "#f87171",
            backgroundColor: "#1e1e1e",
            minHeight: "100vh",
            fontFamily: "monospace",
          }}
        >
          <h2>⚠️ SimulatorPage 렌더링 중 오류가 발생했습니다.</h2>
          <pre style={{ whiteSpace: "pre-wrap", marginTop: 12 }}>
            {String(this.state.error)}
          </pre>
        </div>
      );
    }

    return this.props.children;
  }
}
