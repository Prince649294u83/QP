import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import type { PaperImageAttachment } from "@/lib/ai-api";
import { authFetchBlob } from "@/lib/academic-api";

interface PaperQuestionImagesProps {
  attachments: PaperImageAttachment[];
  className?: string;
}

export function PaperQuestionImages({
  attachments,
  className = "",
}: PaperQuestionImagesProps) {
  if (!attachments.length) {
    return null;
  }

  return (
    <div className={`mt-3 space-y-2 ${className}`.trim()}>
      {attachments.map((attachment, index) => (
        <PaperQuestionImageFigure
          key={`${attachment.image_id || attachment.image_path || attachment.object_url || attachment.data_url || "img"}-${index}`}
          attachment={attachment}
        />
      ))}
    </div>
  );
}

function PaperQuestionImageFigure({ attachment }: { attachment: PaperImageAttachment }) {
  const [src, setSrc] = useState<string | null>(attachment.object_url || attachment.data_url || null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (attachment.object_url || attachment.data_url) {
      return;
    }
    if (!attachment.image_id) {
      setFailed(true);
      return;
    }

    let objectUrl: string | null = null;
    let cancelled = false;

    authFetchBlob(`/academic/documents/images/${attachment.image_id}`)
      .then((blob) => {
        if (cancelled) {
          return;
        }
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      })
      .catch(() => {
        if (!cancelled) {
          setFailed(true);
        }
      });

    return () => {
      cancelled = true;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [attachment.data_url, attachment.image_id, attachment.object_url]);

  return (
    <figure className="rounded-md border border-slate-200 bg-slate-50 p-2 text-center">
      {src ? (
        <img
          src={src}
          alt={attachment.caption || "Question illustration"}
          className="mx-auto max-h-48 w-auto max-w-full object-contain"
        />
      ) : failed ? (
        <div className="flex h-24 items-center justify-center text-xs text-muted-foreground">
          Image unavailable
        </div>
      ) : (
        <div className="flex h-24 items-center justify-center text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
        </div>
      )}
      {(attachment.caption || attachment.document_name || attachment.file_name) && (
        <figcaption className="mt-2 text-[10px] leading-relaxed text-slate-600">
          {attachment.caption || attachment.file_name}
          {attachment.document_name ? ` - ${attachment.document_name}` : ""}
        </figcaption>
      )}
    </figure>
  );
}
