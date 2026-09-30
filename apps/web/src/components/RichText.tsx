import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export function RichText({ text }: { text: string }) {
  return (
    <div className="markdown">
      <Markdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
          img: ({ alt }) => <span className="muted">[Image: {alt || 'embedded image'}]</span>,
        }}
      >
        {text}
      </Markdown>
    </div>
  );
}
