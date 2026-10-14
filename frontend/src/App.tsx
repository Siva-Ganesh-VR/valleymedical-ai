import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import AcceptancePage from "./pages/AcceptancePage";
import AiUsagePage from "./pages/AiUsagePage";
import AuditPage from "./pages/AuditPage";
import BillingPage from "./pages/BillingPage";
import CasePage from "./pages/CasePage";
import ExceptionsPage from "./pages/ExceptionsPage";
import InsightsPage from "./pages/InsightsPage";
import PatientPage from "./pages/PatientPage";
import PatientsPage from "./pages/PatientsPage";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/patients" replace />} />
        <Route path="/patients" element={<PatientsPage />} />
        <Route path="/patients/:patientId" element={<PatientPage />} />
        <Route path="/billing" element={<BillingPage />} />
        <Route path="/billing/cases/:caseId" element={<CasePage />} />
        <Route path="/billing/insights" element={<InsightsPage />} />
        <Route path="/exceptions" element={<ExceptionsPage />} />
        <Route path="/acceptance" element={<AcceptancePage />} />
        <Route path="/ai" element={<AiUsagePage />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="*" element={<p className="empty">This page doesn't exist. Use the menu to find what you need.</p>} />
      </Routes>
    </Layout>
  );
}
