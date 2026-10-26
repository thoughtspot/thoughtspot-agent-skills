const CFG = {
  kind: 'guide', mapTitle: 'How the Liveboard is laid out. Click a tab to see how to read it.',
  need: 'sales by item type, e.g. [sales] [item type]',
  tabs: [
    { no: '02', name: 'Pulse', q: 'How are we doing?', how: 'Read the monthly line first. The dashed line is last year, so the gap is the year on year change.' },
    { no: '03', name: 'Where', q: 'Where does it sell?', how: 'Bubbles and hexes are states. Store coordinates in the model are unreliable, so stores are placed by state.' },
    { no: '04', name: 'What', q: 'What sells?', how: 'Follow the flow from region to family to item type, then check concentration in the Pareto.' },
    { no: '05', name: 'When', q: 'When does it sell?', how: 'The clock and the calendar show the same months two ways. 2021 and the latest year are part years.' },
    { no: '06', name: 'Who', q: 'Who leads?', how: 'Play the race to watch stores change rank. The product table sorts and filters all products.' },
    { no: '07', name: 'Next', q: 'What should we do?', how: 'Outlook and risk views. The projection is labelled as one and follows the scenario you pick.' }
  ],
  build: function () { return {}; }
};
