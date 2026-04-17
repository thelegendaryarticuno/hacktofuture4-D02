import { Routes, Route } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import { ThemeProvider } from "./context/ThemeContext";
import ProtectedRoute from "./components/ProtectedRoute";
import Navbar from "./components/Navbar";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import WorkspacePage from "./pages/WorkspacePage";
import AutoFixReportPage from "./pages/AutoFixReportPage";
import AutoFixFeedbackPage from "./pages/AutoFixFeedbackPage";

function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <Navbar />
        <main>
          <Routes>
            <Route path="/" element={<LoginPage />} />
            <Route
              path="/dashboard"
              element={
                <ProtectedRoute>
                  <DashboardPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/workspace/:id"
              element={
                <ProtectedRoute>  
                  <WorkspacePage />
                </ProtectedRoute>
              }
            />
            <Route path="/autofix/report" element={<AutoFixReportPage />} />
            <Route path="/autofix/feedback" element={<AutoFixFeedbackPage />} />
          </Routes>
        </main>
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
