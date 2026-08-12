import { PageHeader } from "@/components/page-header";
import { AssistantChat } from "@/components/assistant-chat";

export default function EmployeeChatbotPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="HR Assistant"
        description="Ask about leave, benefits, HR policy, and more — grounded in the company knowledge base."
      />
      <AssistantChat />
    </div>
  );
}
