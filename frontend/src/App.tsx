// frontend/src/App.tsx
import { Routes, Route } from "react-router-dom";
import ProtectedRoute from "./components/ProtectedRoute";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import EncounterWorkspace from "./pages/EncounterWorkspace";
import AdminRoute from "./components/AdminRoute"; 
import AdminPage from "./pages/AdminPage";
import SessionExpiredModal from "./components/SessionExpiredModal";
import DiffPage from "./pages/DiffPage";
import AgentRun from "./pages/AgentRun";

export default function App() {
  return (
    <>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
        <Route path="/encounter" element={<ProtectedRoute><EncounterWorkspace /></ProtectedRoute>} />
        <Route path="/diff" element={<ProtectedRoute><DiffPage /></ProtectedRoute>} />
        <Route path="/agent" element={<ProtectedRoute><AgentRun /></ProtectedRoute>} />
        <Route path="/admin" element={<AdminRoute><AdminPage /></AdminRoute>} />
      </Routes>
      <SessionExpiredModal />   {/* persistent overlay: gracefully handles session loss on any page */}
    </>
  );
}