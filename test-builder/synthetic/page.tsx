import Layout0 from '../app/layout.tsx';
import Page from '../app/whee1/page.tsx';

const Entrypoint = () => {
return (
<Layout0><Page /></Layout0>
);
};

ReactDOM.render(<Entrypoint />, document.getElementById('root'));