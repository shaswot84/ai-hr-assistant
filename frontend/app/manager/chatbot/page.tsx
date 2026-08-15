import { ChatbotPage } from "@/components/chatbot-page";

export default function ManagerChatbotPage() {
  return (
    <ChatbotPage
      title="HR Assistant"
      description="Ask about HR policy, procedures, and guidelines — grounded in the indexed knowledge base."
      meta={
        <span className="badge bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-600/20">
          Supervisor-routed
        </span>
      }
    />
  );
}
