/*
 * Copyright (C) 2022 Red Hat, Inc.
 *
 * This program is free software; you can redistribute it and/or modify it
 * under the terms of the GNU Lesser General Public License as published by
 * the Free Software Foundation; either version 2.1 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful, but
 * WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public License
 * along with This program; If not, see <http://www.gnu.org/licenses/>.
 */
import cockpit from 'cockpit';
import React, { useContext, useState } from 'react';

import {
    Card, CardBody, CardHeader, CardTitle,
    PageSection,
    Form,
    SimpleList, SimpleListItem
} from '@patternfly/react-core';

import { AddressContext, Header } from '../Common.jsx';
import { useEvent, useObject } from 'hooks';

export const NetworkHostname = () => {
    const onDoneClicked = () => {
        cockpit.location.go(['summary']);
    };

    return (
        <>
            <Header
              done={onDoneClicked}
              title='Network & Host Name'
            />
            <PageSection>
                <Form isHorizontal>
                    <NetworkConfigurations />
                </Form>
            </PageSection>
        </>
    );
};

const NetworkConfigurations = () => {
    const [deviceConfigurations, setDeviceConfigurations] = useState();
    const address = useContext(AddressContext);

    const networkProxy = useObject(() => {
        const client = cockpit.dbus('org.fedoraproject.Anaconda.Modules.Network', { superuser: 'try', bus: 'none', address });
        const proxy = client.proxy(
            'org.fedoraproject.Anaconda.Modules.Network',
            '/org/fedoraproject/Anaconda/Modules/Network',
        );

        return proxy;
    }, null, [address]);

    useEvent(networkProxy, 'changed', (event, data) => {
        networkProxy.GetDeviceConfigurations().then(ret => {
            console.info(ret);
            setDeviceConfigurations(ret);
        });
    });

    return (
        <Card>
            <CardHeader>
                <CardTitle>Network Devices</CardTitle>
            </CardHeader>
            <CardBody>
                <SimpleList>
                    {deviceConfigurations && deviceConfigurations.map((devCfg) =>
                        <SimpleListItem key={devCfg['device-name'].v}>
                            {devCfg['device-name'].v}
                        </SimpleListItem>)}
                </SimpleList>
            </CardBody>
        </Card>
    );
};
