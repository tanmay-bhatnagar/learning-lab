import { useEffect, useState } from 'react';

export function useSidebarDefault() {
  const [sidebar, setSidebar] = useState(() => window.innerWidth > 700);
  return { sidebar, setSidebar };
}

export function useWindowDragGuards(setDragging: (value: boolean) => void, dragDepthRef: React.RefObject<number>) {
  useEffect(() => {
    const preventFileNavigation = (event: DragEvent) => {
      if (Array.from(event.dataTransfer?.types || []).includes('Files')) {
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'none';
      }
      if (event.type === 'drop' || event.type === 'dragend') {
        setDragging(false);
        dragDepthRef.current = 0;
      }
    };
    window.addEventListener('dragover', preventFileNavigation);
    window.addEventListener('drop', preventFileNavigation);
    window.addEventListener('dragend', preventFileNavigation);
    return () => {
      window.removeEventListener('dragover', preventFileNavigation);
      window.removeEventListener('drop', preventFileNavigation);
      window.removeEventListener('dragend', preventFileNavigation);
    };
  }, [dragDepthRef, setDragging]);
}

export function useTopicSidebarClose(setSidebar: (value: boolean) => void) {
  return () => {
    if (window.innerWidth <= 700) setSidebar(false);
  };
}
