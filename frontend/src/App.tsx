// frontend/src/App.tsx
import { Routes, Route } from "react-router-dom";
import ProtectedRoute from "./components/ProtectedRoute";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import EncounterWorkspace from "./pages/EncounterWorkspace";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
      <Route path="/encounter" element={<ProtectedRoute><EncounterWorkspace /></ProtectedRoute>} /> 
    </Routes>
  );
}