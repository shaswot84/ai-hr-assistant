import { PageHeader } from "@/components/page-header";
import { KnowledgeChat } from "@/components/knowledge-chat";

export default function EmployeeChatbotPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="HR Policy Chatbot"
        description="Ask about leave, benefits, HR policy, and more — grounded in the company knowledge base."
      />
      <KnowledgeChat />
    </div>
  );
}
