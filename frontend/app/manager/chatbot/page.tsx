import { PageHeader } from "@/components/page-header";
import { KnowledgeChat } from "@/components/knowledge-chat";

export default function ManagerChatbotPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="HR Policy Chatbot"
        description="Ask questions about HR policy and get answers grounded in the indexed knowledge base."
        meta={
          <span className="badge bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-600/20">
            Knowledge service
          </span>
        }
      />
      <KnowledgeChat />
    </div>
  );
}
