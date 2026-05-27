import { Navigate, Route, Routes } from "react-router-dom";

import AppShell from "./components/AppShell";
import ArtifactsPage from "./pages/ArtifactsPage";
import ReportsPage from "./pages/ReportsPage";
import RunsPage from "./pages/RunsPage";
import SettingsPage from "./pages/SettingsPage";
import StocksPage from "./pages/StocksPage";
import TodayPage from "./pages/TodayPage";

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route index element={<TodayPage />} />
        <Route path="/stocks" element={<StocksPage />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/runs" element={<RunsPage />} />
        <Route path="/runs/:uiRunId" element={<RunsPage />} />
        <Route path="/artifacts" element={<ArtifactsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
