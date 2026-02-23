import { BrowserRouter, Routes, Route } from "react-router-dom"
import Layout from "@/components/shared/Layout"
import HomePage from "@/pages/HomePage"
import InterviewPage from "@/pages/InterviewPage"
import FeedbackPage from "@/pages/FeedbackPage"
import ResumePage from "@/pages/ResumePage"

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/interview/:sessionId" element={<InterviewPage />} />
          <Route path="/feedback/:sessionId" element={<FeedbackPage />} />
          <Route path="/resume/" element={<ResumePage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
