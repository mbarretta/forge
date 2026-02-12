import { BrowserRouter as Router, Routes, Route, Link } from "react-router-dom";
import ToolListPage from "./pages/ToolListPage";
import ToolRunPage from "./pages/ToolRunPage";
import JobHistoryPage from "./pages/JobHistoryPage";
import "./App.css";

function App() {
  return (
    <Router>
      <div className="app">
        <header className="header">
          <div className="container">
            <div className="header-content">
              <h1>
                <Link to="/" className="logo">
                  FORGE
                </Link>
              </h1>
              <p className="tagline">Chainguard Field Engineering Toolkit</p>
              <nav className="nav">
                <Link to="/" className="nav-link">
                  Tools
                </Link>
                <Link to="/history" className="nav-link">
                  Job History
                </Link>
              </nav>
            </div>
          </div>
        </header>

        <main className="main">
          <Routes>
            <Route path="/" element={<ToolListPage />} />
            <Route path="/tool/:toolName" element={<ToolRunPage />} />
            <Route path="/history" element={<JobHistoryPage />} />
          </Routes>
        </main>

        <footer className="footer">
          <div className="container">
            <p>FORGE v0.1.0 - Apache 2.0 License</p>
          </div>
        </footer>
      </div>
    </Router>
  );
}

export default App;
