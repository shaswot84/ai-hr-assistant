import { ComingSoon } from "@/components/coming-soon";

export default function ManagerIngestionPage() {
  return (
    <ComingSoon
      title="Document Ingestion"
      description="Upload HR policy documents to power the chatbot's knowledge base — coming later."
      icon={
        <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M12 12v9m0-9l-3 3m3-3l3 3" />
        </svg>
      }
    />
  );
}
