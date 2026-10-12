import type { DialogueIdeaStatus, DialogueMap as DialogueMapData } from '../api'

const STATUS_LABEL: Record<DialogueIdeaStatus, string> = {
  adopted: 'принята',
  open: 'открыта',
  rejected: 'отклонена',
}

export function DialogueMapView({
  dialogue,
  onBuild,
}: {
  dialogue: DialogueMapData | null
  onBuild: () => void
}) {
  if (!dialogue) {
    return <p className="consensus-loading">Загрузка карты…</p>
  }

  const hasMap = dialogue.available && dialogue.questions.length > 0

  return (
    <div className="ibis">
      {dialogue.busy ? <p className="consensus-loading">Собираем карту по расшифровке…</p> : null}
      {dialogue.error ? (
        <p className="consensus-error" role="alert">
          {dialogue.error}
        </p>
      ) : null}
      {!dialogue.busy && !hasMap ? (
        <div className="ibis-empty">
          <p className="consensus-empty">
            {dialogue.available
              ? 'В разговоре не нашлось вопросов с разными идеями или доводами.'
              : 'Карта показывает вопросы, идеи и доводы за и против — только то, что прозвучало на встрече.'}
          </p>
          <button type="button" className="ibis-build" onClick={onBuild}>
            {dialogue.available ? 'Собрать заново' : 'Собрать карту'}
          </button>
        </div>
      ) : null}
      {hasMap ? (
        <>
          <p className="ibis-legend">
            Вопрос слева, идеи справа. Плюс — довод за, минус — довод против.
          </p>
          <div className="ibis-map">
            {dialogue.questions.map((question, questionIndex) => (
              <article className="ibis-row" key={`${question.text}-${questionIndex}`}>
                <div className="ibis-question">
                  <span className="ibis-mark" aria-hidden="true">
                    ?
                  </span>
                  <p>{question.text}</p>
                </div>
                <div className="ibis-ideas">
                  {question.ideas.length === 0 ? (
                    <p className="ibis-none">Идей не прозвучало.</p>
                  ) : (
                    question.ideas.map((idea, ideaIndex) => (
                      <div
                        className={`ibis-idea ibis-idea-${idea.status}`}
                        key={`${idea.text}-${ideaIndex}`}
                      >
                        <div className="ibis-idea-head">
                          <p>{idea.text}</p>
                          <span className="ibis-status">{STATUS_LABEL[idea.status]}</span>
                        </div>
                        {idea.author ? <p className="ibis-author">{idea.author}</p> : null}
                        {idea.pros.length > 0 || idea.cons.length > 0 ? (
                          <ul className="ibis-args">
                            {idea.pros.map((argument, index) => (
                              <li className="ibis-pro" key={`pro-${argument.text}-${index}`}>
                                <span className="ibis-mark" aria-hidden="true">
                                  +
                                </span>
                                <span>
                                  {argument.text}
                                  {argument.author ? (
                                    <span className="ibis-author"> · {argument.author}</span>
                                  ) : null}
                                </span>
                              </li>
                            ))}
                            {idea.cons.map((argument, index) => (
                              <li className="ibis-con" key={`con-${argument.text}-${index}`}>
                                <span className="ibis-mark" aria-hidden="true">
                                  −
                                </span>
                                <span>
                                  {argument.text}
                                  {argument.author ? (
                                    <span className="ibis-author"> · {argument.author}</span>
                                  ) : null}
                                </span>
                              </li>
                            ))}
                          </ul>
                        ) : null}
                      </div>
                    ))
                  )}
                </div>
              </article>
            ))}
          </div>
          {!dialogue.busy ? (
            <button type="button" className="ibis-rebuild" onClick={onBuild}>
              Собрать заново
            </button>
          ) : null}
        </>
      ) : null}
    </div>
  )
}
