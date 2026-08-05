import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const components: Components = {
  h1: ({ children }) => (
    <h1 className="text-2xl leading-tight font-semibold tracking-[-0.02em] lg:text-xl">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-xl leading-snug font-semibold tracking-[-0.015em] lg:text-lg">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="text-lg leading-snug font-semibold lg:text-base">
      {children}
    </h3>
  ),
  p: ({ children }) => <p>{children}</p>,
  ul: ({ children }) => (
    <ul className="marker:text-secondary list-disc space-y-2 pl-6">
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="marker:text-secondary list-decimal space-y-2 pl-6">
      {children}
    </ol>
  ),
  li: ({ children }) => <li className="pl-1">{children}</li>,
  blockquote: ({ children }) => (
    <blockquote className="border-line-strong text-secondary border-l pl-4">
      {children}
    </blockquote>
  ),
  a: ({ children, href }) => (
    <a
      className="decoration-line-strong hover:decoration-foreground underline underline-offset-4"
      href={href}
      rel="noreferrer"
      target="_blank"
    >
      {children}
    </a>
  ),
  code: ({ children, className }) => (
    <code
      className={
        className
          ? className
          : "bg-subtle rounded-[var(--radius-xs)] px-1.5 py-0.5 text-[0.9em]"
      }
    >
      {children}
    </code>
  ),
  pre: ({ children }) => (
    <pre className="bg-subtle overflow-x-auto rounded-[var(--radius-lg)] p-4 text-sm leading-6">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <div className="border-line overflow-x-auto rounded-[var(--radius-lg)] border">
      <table className="w-full min-w-[36rem] border-collapse text-left text-sm">
        {children}
      </table>
    </div>
  ),
  th: ({ children }) => (
    <th className="bg-subtle border-line border-b px-3 py-2 font-medium">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border-line border-b px-3 py-2 align-top last:border-b-0">
      {children}
    </td>
  ),
  hr: () => <hr className="border-line" />,
};

export function MessageContent({ content }: { content: string }) {
  return (
    <div className="max-w-[72ch] text-[17px] leading-7.5 break-words lg:text-sm lg:leading-7 [&>*+*]:mt-5 lg:[&>*+*]:mt-4">
      <ReactMarkdown components={components} remarkPlugins={[remarkGfm]}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
