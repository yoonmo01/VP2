import React from "react";

const AIDisclaimerScroll = ({ COLORS }) => {
  const message =
    "본 콘텐츠는 AI 기술 시연을 위한 가상 시나리오입니다. 실제 범죄에 악용 시 형법 제347조(사기)에 의해 10년 이하 징역 또는 2천만원 이하 벌금에 처해질 수 있습니다. 범죄 예방 교육 목적으로만 사용해 주시기 바랍니다. ";

  return (
    <div className="flex items-center">
      {/* AI 디스클레임러 스크롤 */}
      <div
        className="overflow-hidden border-t border-b rounded mr-3"
        style={{
          borderColor: COLORS.border,
          width: "600px",
          height: "40px",
        }}
      >
        <div className="py-2 whitespace-nowrap animate-scroll">
          <span className="text-xs" style={{ color: COLORS.sub }}>
            {message + message + message}
          </span>
        </div>
      </div>

      <style>{`
        @keyframes scroll {
          0% { transform: translateX(0); }
          100% { transform: translateX(-33.33%); }
        }

        .animate-scroll {
          display: inline-block;
          animation: scroll 45s linear infinite;
        }
      `}</style>
    </div>
  );
};

export default AIDisclaimerScroll;
